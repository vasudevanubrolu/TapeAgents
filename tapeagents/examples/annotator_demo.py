import logging

from langchain_community.tools.tavily_search import TavilySearchResults
from tapeagents.demo import Demo
from tapeagents.dialog import Dialog, DialogContext
from tapeagents.environment import LangchainToolEnvironment
from tapeagents.llms import LiteLLM
from tapeagents.rendering import BasicRenderer

from .annotator import GroundednessAnnotator
from .openai_function_calling import FunctionCallingAgent

logging.basicConfig(level=logging.INFO)


def try_annotator_demo():
    small_llm = LiteLLM(model_name="gpt-3.5-turbo")
    big_llm = LiteLLM(model_name="gpt-4-turbo")
    agent = FunctionCallingAgent.create(small_llm)
    environment = LangchainToolEnvironment(tools=[TavilySearchResults()])
    init_dialog = Dialog(context=DialogContext(tools=environment.get_tool_schemas()), steps=[])
    demo = Demo(agent, init_dialog, environment, BasicRenderer(), GroundednessAnnotator.create(big_llm))
    demo.launch()


if __name__ == "__main__":
    try_annotator_demo()
