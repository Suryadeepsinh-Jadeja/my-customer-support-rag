# main.py - terminal client for the customer support assistant (development / demos).
#
#   python -m customer_support_chat.app.main [--graph-image]

import argparse
import os

from customer_support_chat.app.core.errors import SupportError
from customer_support_chat.app.core.logger import logger
from customer_support_chat.app.core.settings import get_settings
from customer_support_chat.app.graph import get_graph
from customer_support_chat.app.services.chat_service import ChatResult, ChatService


def save_graph_image() -> None:
    try:
        # Generate the graph object with xray=True to include node details
        graph_image = get_graph().get_graph(xray=True).draw_mermaid_png()
        os.makedirs("./graphs", exist_ok=True)
        image_path = os.path.join("./graphs", "multi-agent-rag-system-graph.png")
        with open(image_path, "wb") as f:
            f.write(graph_image)
        print(f"Graph saved at {image_path}")
    except Exception as e:
        logger.error(f"An error occurred while generating the graph visualization: {e}")
        print("Graph visualization could not be generated. Continuing without it.")


def show(result: ChatResult) -> None:
    print(f"\n[{result.agent}] {result.response}")
    if result.sources:
        print("Sources: " + "; ".join(f"{s['document_name']} - {s['section']}" for s in result.sources))
    for action in result.pending_actions:
        print(f"\n  Pending action: {action.title}")
        for detail in action.details:
            print(f"    {detail['label']}: {detail['value']}")


def main():
    parser = argparse.ArgumentParser(description="Chat with the customer support assistant.")
    parser.add_argument("--graph-image", action="store_true", help="Save the graph as a PNG first.")
    args = parser.parse_args()

    if args.graph_image:
        save_graph_image()

    service = ChatService(graph_factory=get_graph)
    session = None

    demo_id = get_settings().DEMO_PASSENGER_ID
    passenger_id = input(f"Passenger ID [{demo_id or 'blank = guest'}]: ").strip() or demo_id
    if passenger_id:
        reference = input("Booking reference or ticket number: ").strip()
        try:
            session = service.authenticate(passenger_id, reference)
            print("Signed in.")
        except SupportError as e:
            print(e.user_message, "Continuing as a guest (policy questions only).")

    conversation_id = None
    print("Type 'quit' to exit.\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"quit", "exit", "q"}:
            print("Goodbye!")
            break
        if not user_input:
            continue
        try:
            result = service.chat(user_input, conversation_id=conversation_id, session=session)
            conversation_id = result.conversation_id
            show(result)
            while result.status == "confirmation_required":
                answer = input(
                    "\nDo you approve? Type 'y' to continue; otherwise explain what you'd like instead: "
                ).strip()
                approved = answer.lower() in {"y", "yes"}
                result = service.confirm(
                    conversation_id, approved, None if approved else answer, session=session
                )
                show(result)
        except SupportError as e:
            print(f"\n{e.user_message}")


if __name__ == "__main__":
    main()
