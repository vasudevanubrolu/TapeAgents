#!/bin/bash

INPUT_PATH=".local/agent_tapes/teacher_agent_predicted_tapes.yaml"
OUTPUT_PREFIX=".local/user_tapes"

# List of user simulator agents
USER_SIMULATORS=(
  ask_about_docs
  happy_path
  init_message_ask
  init_message_short
  invalid_value_3
  multislot_instruct3a
  multislot_instruct3b
  multislot_instruct3c
  skip_optional
  skip_required
)

# Loop over each user simulator agent
for USER_SIMULATOR in "${USER_SIMULATORS[@]}"; do
  # Run the Python script with the specified arguments
  python examples/form_filler/dev/run_user_simulator.py \
    input_dialogues_path="${INPUT_PATH}" \
    output_path="${OUTPUT_PREFIX}/${USER_SIMULATOR}" \
    user_simulator_agent="${USER_SIMULATOR}" \
    llm@user_simulator_agent.llms=vllm_llama3_8b_temp1 \
    max_continuable_tapes=30 \
    n_workers=4
done

# Visualize 
python examples/form_filler/dev/visualize_formfiller_tapes.py ${OUTPUT_PREFIX}