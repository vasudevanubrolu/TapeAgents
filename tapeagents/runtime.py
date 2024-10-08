import enum
import logging
from typing import Generator, Generic

from pydantic import BaseModel, Field
from termcolor import colored

from .agent import Agent
from .core import AgentEvent, FinalStep, Observation, Step, Tape, TapeType
from .environment import Environment, ExternalObservationNeeded, NoActionsToReactTo
from .rendering import step_view
from .utils import FatalError, diff_dicts

logger = logging.getLogger(__name__)


class MainLoopStatus(enum.Enum):
    OK = "ok"
    FINISHED = "finished"
    NO_ACTIONS = "no_actions"
    EXTERNAL_INPUT_NEEDED = "external_input_needed"
    UNKNOWN_ACTION = "unknown_action"


class MainLoopEvent(BaseModel, Generic[TapeType]):
    # TODO: validate that event must have only either the agent or the environment data
    agent_event: AgentEvent[TapeType] | None = Field(default=None, description="Propagates all the agent events")
    agent_tape: TapeType | None = Field(default=None, description="The tape after agent.run()")
    observation: Observation | None = Field(
        default=None, description="One of the observations produced by environment.react()"
    )
    env_tape: TapeType | None = Field(default=None, description="The tape after environment.react()")
    status: MainLoopStatus = MainLoopStatus.OK


class MainLoopStream(Generic[TapeType]):
    def __init__(self, generator: Generator[MainLoopEvent[TapeType], None, None]):
        self.generator = generator

    def __bool__(self):
        return self.generator is not None

    def __iter__(self):
        if self.generator is None:
            raise ValueError("can't iterate a null stream")
        return self

    def __next__(self) -> MainLoopEvent:
        if self.generator is None:
            raise StopIteration
        return next(self.generator)

    def agent_events(self) -> Generator[AgentEvent[TapeType], None, None]:
        for event in self:
            if event.agent_event:
                yield event.agent_event

    def get_final_tape(self) -> TapeType:
        """Return the last tape by either the agent or the environment."""
        last_final_tape = None
        for event in self:
            if event.agent_tape:
                last_final_tape = event.agent_tape
            if event.env_tape:
                last_final_tape = event.env_tape
        if last_final_tape is not None:
            return last_final_tape
        raise ValueError("No tape by either the agent or the environment")


def main_loop(
    agent: Agent[TapeType],
    start_tape: TapeType,
    environment: Environment,
    max_loops: int = -1,
) -> MainLoopStream[TapeType]:
    """
    Main loop of the agent-environment interaction. The agent is run on the tape, then the environment reacts to the
    agent's tape, then the agent is run on the environment's tape, and so on.
    The loop stops when the agent emits a final step or the environment emits a final step,
    or the maximum number of loops is reached.

    :param agent: Agent object
    :param start_tape: initial tape
    :param environment: Environment object
    :param max_loops: maximum number of loops, -1 for infinite

    :return: generator of MainLoopEvent objects
    """

    def _implementation():
        n_loops = 0
        tape = start_tape
        event = None
        while n_loops < max_loops or max_loops == -1:
            # --- RUN THE AGENT ---
            for event in agent.run(tape):
                yield MainLoopEvent(agent_event=event)
                if event.step:
                    logger.debug(colored(f"AGENT: {step_view(event.step)}", "green"))
                if event.final_tape:
                    break
            assert event and event.final_tape
            agent_tape = event.final_tape
            yield MainLoopEvent(agent_tape=agent_tape)

            # --- RUN THE ENVIRONMENT ---
            if isinstance(agent_tape.steps[-1], FinalStep):
                logger.debug(f"Agent emitted final step {agent_tape.steps[-1]}")
                yield MainLoopEvent(status=MainLoopStatus.FINISHED)
                return
            try:
                tape = environment.react(agent_tape)
            except NoActionsToReactTo as e:
                yield MainLoopEvent(status=MainLoopStatus.NO_ACTIONS)
                return
            except ExternalObservationNeeded as e:
                yield MainLoopEvent(status=MainLoopStatus.EXTERNAL_INPUT_NEEDED)
                return
            for observation in tape[len(agent_tape) :]:
                logger.debug(colored(f"ENV: {step_view(observation, trim=True)}", "yellow"))
                yield MainLoopEvent(observation=observation)
            yield MainLoopEvent[TapeType](env_tape=tape)

            # --- REPEAT ---
            n_loops += 1

    return MainLoopStream(_implementation())


def replay_tape(
    agent: Agent[TapeType],
    tape: TapeType,
    env: Environment[TapeType] | None = None,
    start_tape: TapeType | None = None,
    reuse_observations: bool = False,
    stop_on_mismatch: bool = True,
) -> bool:
    """
    Replay the tape with the agent and compare the steps with the old tape.
    Count mismatches and print diffs of them.

    :param agent: Agent object
    :param tape: Old tape object
    :param env: Environment object
    :param start_tape: initial tape, if None, the first observations of the tape are used
    :param reuse_observations: reuse observations from the tape instead of calling the environment
    :param stop_on_mismatch: stop the replay on the first mismatch

    :return: True if all steps match, False otherwise
    """
    if env is None and not reuse_observations:
        raise ValueError("Environment is required when not reusing observations")
    match: bool = True
    if start_tape is None:
        start_steps: list[Step] = []
        for step in tape.steps:
            if isinstance(step, Observation):
                start_steps.append(step)
            else:
                break
        start_tape = tape.model_copy(update=dict(steps=start_steps))

    event = None
    new_tape: TapeType = start_tape
    i = len(start_tape)
    while i < len(tape):
        for event in agent.run(new_tape):
            if event.step:
                step_dict = event.step.llm_dict()
                old_step_dict = tape.steps[i].llm_dict()
                i += 1
                kind = step_dict.get("kind")
                old_kind = old_step_dict.get("kind")
                if kind != old_kind:
                    logger.error(
                        f"Step {i} kind mismatch: Old {old_kind}, New {kind}\nOld step: {old_step_dict}\nNew step: {step_dict}"
                    )
                    match = False
                    if stop_on_mismatch:
                        return False
                elif old_step_dict != step_dict:
                    logger.error(f"Step {i} mismatch")
                    logger.error(diff_dicts(old_step_dict, step_dict))
                    match = False
                    if stop_on_mismatch:
                        return False
                else:
                    logger.debug(f"Step {i} ok")
            if event.final_tape:
                break
        assert event and event.final_tape
        agent_tape = event.final_tape
        if isinstance(agent_tape.steps[-1], FinalStep):
            logger.debug(f"Agent emitted final step {agent_tape.steps[-1]}")
            break

        if reuse_observations:
            observations: list[Step] = []
            for step in tape.steps[len(agent_tape) :]:
                if isinstance(step, Observation):
                    observations.append(step)
                else:
                    break
            if len(observations):
                logger.debug(f"Reusing {len(observations)} observations from tape")
            new_tape = agent_tape + observations
            i += len(observations)
        else:
            assert env is not None
            new_tape = env.react(agent_tape)
            observations = new_tape.steps[len(agent_tape) :]
            for observation in observations:
                step_dict = observation.llm_dict()
                old_step_dict = tape.steps[i].llm_dict()
                i += 1
                if old_step_dict != step_dict:
                    logger.error(f"Observation {i} mismatch")
                    logger.error(diff_dicts(old_step_dict, step_dict))
                    match = False
                    if stop_on_mismatch:
                        return False
                else:
                    logger.debug(f"Observation {i} ok")

                if isinstance(observation, FinalStep):
                    logger.debug(f"Environment emitted final step {observation}")
                    break
    return match


def replay_tapes(
    agent: Agent[TapeType],
    tapes: list[TapeType],
    env: Environment[TapeType] | None = None,
    reuse_observations: bool = False,
    pause_on_error: bool = False,
) -> int:
    """
    Validate the list of tapes with the agent and environment.
    Check that the agent produce exactly the same steps as the original ones.
    Returns the number of failed tapes.
    """
    ok = 0
    fails = 0
    for i, tape in enumerate(tapes):
        logger.debug(f"Tape {i}")
        try:
            if not replay_tape(agent, tape, env, reuse_observations=reuse_observations):
                raise FatalError("Tape mismatch")
            ok += 1
        except FatalError as f:
            logger.error(colored(f"Fatal error: {f}, skip tape", "red"))
            fails += 1
            if pause_on_error:
                input("Press Enter to continue...")

        logger.debug(colored(f"Ok: {ok}, Fails: {fails}", "green"))
    return fails
