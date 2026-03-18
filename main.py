from openai import OpenAI
from dotenv import load_dotenv
from core.agents.saved_agents import manager, communication_officer
from core.tools.place_order import place_order

load_dotenv()

# INITIATE SHARED STATE
state = {
    "shortages": [],
    "stock_details": {},
    "options": [],
    "supplier_options": {},
    "pending_orders": [],
    "receipt": [],      # New field for the final table
    "total_spent": 0.0, # New field for math
    "human_approval": False,
    "current_agent": manager,
    "order_confirmed": False,
    "email_draft": "",
    "email_sent": False
}


def print_receipt(receipt, total_spent, title):
    print("\n" + "="*60)
    print(f"{title:^60}")
    print("="*60)

    if receipt:
        print(f"{'ITEM':<25} | {'SUPPLIER':<20} | {'QTY':<5} | {'TOTAL':<10}")
        print("-" * 65)

        for row in receipt:
            item_name = row[0][:23]
            supplier = row[1][:18]
            qty = str(row[2])
            total = str(row[4])
            print(f"{item_name:<25} | {supplier:<20} | {qty:<5} | {total:<10}")

        print("-" * 65)
        print(f"{'GRAND TOTAL':<53} | £{total_spent:.2f}")
    else:
        print("❌ No orders were finalized in this session.")

    print("="*60)

def run_system():
    print("\n" + "="*50)
    print("🚀 NHS-FLOW SYSTEM STARTED")
    print("="*50)

    # 1. INITIAL ANALYSIS LOOP
    user_query = "Are we in stock? If not, find suppliers."
    response = state["current_agent"].run(
        query=user_query,
        state=state,
        openai=OpenAI()
    )

    # 2. HUMAN CHECKPOINT (Financial Approval)
    if state["shortages"] and not state["human_approval"]:
        print("\n" + "-"*50)
        print(f"🚨 AUDIT REPORT: Critical Shortages Detected: {state['shortages']}")
        print("-"*50)
        
        choice = input("\n👤 SUPERVISOR: Do you approve placing the order? (yes/no): ").strip().lower()
        
        if choice in {"yes", "y"}:
            state["human_approval"] = True
            
            # --- FORCE EXECUTION PROMPT ---
            print("\n⚙️ AUTHORIZING PURCHASE AGENTS...")
            order_query = (
                f"AUTHORIZATION GRANTED. The human has approved the purchase request. "
                f"IMMEDIATELY use the 'place_order' tool for these items: {state['shortages']}. "
                f"REQUIREMENTS: "
                f"1. Select the Cheapest NHS-Approved Supplier found in history. "
                f"2. Quantity = (Threshold - Current Stock) + 10 buffer. "
                f"3. DO NOT ask for permission again. EXECUTE the tool now."
            )
            
            order_response = state["current_agent"].run(
                query=order_query,
                state=state,
                openai=OpenAI()
            )
            print(f"\n✅ AGENT REPORT: {order_response}")

        else:
            print("🛑 Order denied by Supervisor.")
            return



    # 3. COMMUNICATION CHECKPOINT
    if state["order_confirmed"] and state["pending_orders"]:
        print("\n" + "-"*50)
        print("🧾 ORDER SUMMARY READY FOR REVIEW")
        print_receipt(state["receipt"], state["total_spent"], "PROPOSED PURCHASE RECEIPT")

        print("📨 PREPARING SUPPLIER CONFIRMATION EMAILS...")

        email_lines = []
        for order in state["pending_orders"]:
            email_lines.append(
                f"- {order['item_name']}, Quantity: {order['quantity']}, Cost per unit: £{order['cost_per_unit']}, "
                f"Total cost: £{order['total_cost']}, Location: {order['location']}, Supplier: {order['supplier']}, "
                f"Delivery: {order['delivery']}, Supplier Email: {order['contact_email']}, Supplier Phone: {order['contact_phone']}"
            )

        supplier_contacts = [
            {
                "supplier": order["supplier"],
                "email": order["contact_email"],
                "phone": order["contact_phone"],
            }
            for order in state["pending_orders"]
        ]

        email_schema = {
        "subject": "Procurement Order Confirmation for Medical Supplies",
        "To": "{supplier_contacts}",
        "body": "Dear {supplier_name},\n\nWe are writing to confirm our recent procurement order for medical supplies. Below are the details of the order:\n\n{order_details}\n\nPlease confirm receipt of this order and provide an estimated delivery date.\n\nThank you for your prompt attention to this matter.\n\nBest regards,\nNHS Procurement Team",
        "contact_info": {"NHS Procurement Team\nEmail: procurement@nhs.uk", "Phone: +44 20 7946 0000"}
    }

        email_context = (
            f"Draft a supplier confirmation email using this template: {email_schema}. "
            f"Order details:\n" + "\n".join(email_lines) + "\n"
            f"Total Value: £{state['total_spent']:.2f}. "
            f"Supplier contact details: {supplier_contacts}. Mention supplier name and contact info clearly in the email. "
            f"Include the supplier name and their contact info clearly in the email."
        )
        draft = communication_officer.run(email_context, state, OpenAI()) # Reuse the run method
        
        state["email_draft"] = draft
        print(f"\n--- DRAFT EMAIL ---\n{draft}\n-------------------")

        confirm = input("\n👤 SUPERVISOR: Send this email? (yes/no): ").strip().lower()
        if confirm in {"yes", "y"}:
            for order in state["pending_orders"]:
                result = place_order(
                    order["item_name"],
                    order["quantity"],
                    order["supplier"],
                    order["cost_per_unit"]
                )
                print(result)
            print("\n🚀 Email Sent Successfully!")
            state["email_sent"] = True

    # 4. FINAL MARKDOWN RECEIPT
    print("\n\n")
    print_receipt(state["receipt"] if state["email_sent"] else [], state["total_spent"], "🏥 NHS-FLOW FINAL SESSION RECEIPT")
    print()

if __name__ == "__main__":
    run_system()
