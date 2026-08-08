from brain.llm import LLM


def main() -> None:
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


if __name__ == "__main__":
    main()