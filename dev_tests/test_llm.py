from brain.llm import LLM

brain = LLM()

while True:
    question = input("You: ")

    if question.lower() == "exit":
        break

    try:
        answer = brain.ask(question)
        print("\nJARVIS:", answer)

    except Exception as e:
        print("Error:", e)