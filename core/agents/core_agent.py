import json
import os
# Import your real functions
from core.tools.check_stock_function import check_stock
from core.tools.get_supplier_function import get_supplier
from core.tools.place_order import place_order

# --- ABSOLUTE PATH SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR) if "core" in BASE_DIR else BASE_DIR
INVENTORY_PATH = os.path.join(PROJECT_ROOT, "data", "inventory.json")
SUPPLIER_PATH = os.path.join(PROJECT_ROOT, "data", "suppliers.json")


def _load_inventory_details():
    with open(INVENTORY_PATH, 'r', encoding='utf-8-sig') as f:
        inventory = json.load(f)

    return {
        item.get("name", ""): item
        for item in inventory
        if item.get("name")
    }


def _parse_supplier_options(raw_result):
    try:
        options = json.loads(raw_result)
    except (TypeError, json.JSONDecodeError):
        return []

    if not isinstance(options, list):
        return []

    approved = []
    for option in options:
        approved_flag = str(option.get("nhs_approved", "")).strip().lower()
        if approved_flag in {"yes", "true"}:
            approved.append(option)

    approved.sort(
        key=lambda option: (
            float(option.get("cost", float("inf"))),
            int(str(option.get("delivery", "999")).split()[0])
        )
    )
    return approved


def _load_suppliers():
    with open(SUPPLIER_PATH, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def _format_order_summary(state):
    pending_orders = state.get("pending_orders", []) if state else []
    if not pending_orders:
        return "No orders are currently staged."

    lines = []
    for index, order in enumerate(pending_orders, start=1):
        lines.append(
            f"{index}. {order['item_name']}: {order['quantity']} units from "
            f"{order['supplier']} at £{order['cost_per_unit']:.2f} each."
        )

    total_spent = float(state.get("total_spent", 0.0)) if state else 0.0
    return (
        "All orders have been staged for placement, awaiting email confirmation "
        "for inventory updates. Here's a summary of the items prepared for order:\n\n"
        + "\n".join(lines)
        + f"\n\nTotal staged value: £{total_spent:.2f}"
    )


def _resolve_order_quantity(item_name, state):
    stock_details = state.get("stock_details", {}) if state else {}
    item_details = stock_details.get(item_name)

    if not item_details:
        item_details = _load_inventory_details().get(item_name, {})

    current_stock = int(item_details.get("quantity", item_details.get("current_stock", 0)))
    min_threshold = int(item_details.get("critical_threshold", item_details.get("min_threshold", 0)))
    shortage_gap = max(min_threshold - current_stock, 0)
    return shortage_gap + 10


def _resolve_supplier(item_name, state):
    supplier_options = state.get("supplier_options", {}) if state else {}
    options = supplier_options.get(item_name, [])

    if not options and state:
        for entry in state.get("options", []):
            if not isinstance(entry, str) or not entry.startswith(f"{item_name}: "):
                continue
            _, raw_result = entry.split(": ", 1)
            options = _parse_supplier_options(raw_result)
            if options:
                break

    if not options:
        raw_result = get_supplier(item_name, SUPPLIER_PATH)
        options = _parse_supplier_options(raw_result)
        if state is not None:
            state.setdefault("supplier_options", {})[item_name] = options

    if not options:
        return {}

    best_option = options[0]
    suppliers_by_name = {
        supplier.get("name", ""): supplier
        for supplier in _load_suppliers()
    }
    supplier_name = best_option.get("supplier", "")
    supplier_record = suppliers_by_name.get(supplier_name, {})
    return {
        "supplier": supplier_name,
        "cost_per_unit": float(best_option.get("cost", 0.0)),
        "delivery": best_option.get("delivery", ""),
        "contact_email": supplier_record.get("contact", {}).get("email", ""),
        "contact_phone": supplier_record.get("contact", {}).get("phone", ""),
    }

class Agent:
    def __init__(self, name, instructions, model="gpt-4o-mini", tools=None):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools if isinstance(tools, list) else [tools] if tools else []

    def run(self, query, state, openai):
        print(f"\n🧠 {self.name} STARTING RUN...")
        
        messages = [
            {"role": "system", "content": self.instructions},
            {"role": "user", "content": query}
        ]

        while True:
            # 1. Call OpenAI
            response = openai.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools if self.tools else None,
            )
            
            msg = response.choices[0].message

            # 2. If AI just talks (no tools), return the text
            if not msg.tool_calls:
                return msg.content

            # 3. If AI calls tools, we MUST process ALL of them
            messages.append(msg)
            
            for tool in msg.tool_calls:
                func_name = tool.function.name
                args = json.loads(tool.function.arguments)
                print(f"   🛠️ {self.name} CALLING TOOL: {func_name}")

                result = "Error: Tool not found."

                # --- TOOL A: STOCK AUDITOR ---
                if "stock_auditor" in func_name or func_name == "check_stock":
                    raw_result = check_stock(INVENTORY_PATH)
                    print(f"      🔙 STOCK RESULT: {str(raw_result)[:50]}...")
                    
                    result = f"Stock Check Result: {raw_result}"
                    
                    if "CRITICAL" in str(raw_result):
                        print("      🚨 CRITICAL SHORTAGE DETECTED")
                        try:
                            data = json.loads(raw_result)
                            if state is not None:
                                state["stock_details"] = data
                            shortages = []
                            for k, v in data.items():
                                # Robust check for nested dicts or strings
                                if (isinstance(v, str) and "CRITICAL" in v) or \
                                   (isinstance(v, dict) and "CRITICAL" in str(v)):
                                    shortages.append(k)
                            
                            print(f"      📋 PARSED SHORTAGES: {shortages}")
                            if state is not None:
                                state["shortages"] = shortages
                        except Exception as e:
                            print(f"      ❌ PARSING ERROR: {e}")

                # --- TOOL B: PROCUREMENT SPECIALIST ---
                elif "procurement" in func_name or func_name == "get_supplier":
                    # Smart Item Detection
                    current_shortages = state.get("shortages", [])
                    item_to_find = None
                    query_text = (
                        args.get('query', '')
                        or args.get('item_name', '')
                    ).lower()
                    
                    # check if the query mentions a specific shortage
                    for short_item in current_shortages:
                        if short_item.lower() in query_text:
                            item_to_find = short_item
                            break
                    if not item_to_find:
                        item_to_find = current_shortages[0] if current_shortages else "N95 Respirator Mask"

                    print(f"      🔎 LOOKING FOR SUPPLIER FOR: {item_to_find}")

                    cached_options = state.get("supplier_options", {}).get(item_to_find, []) if state else []
                    if cached_options:
                        print(f"      ♻️ USING CACHED SUPPLIER OPTIONS FOR: {item_to_find}")
                        raw_result = json.dumps(cached_options)
                        result = f"Supplier Options for {item_to_find}: {raw_result}"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool.id,
                            "content": str(result)
                        })
                        continue
                    
                    # Call function safely
                    try:
                        raw_result = get_supplier(item_to_find, SUPPLIER_PATH)
                    except TypeError:
                        raw_result = get_supplier(SUPPLIER_PATH, item_to_find)
                    
                    print(f"      🔙 SUPPLIER FOUND: {str(raw_result)[:50]}...")
                    result = f"Supplier Options for {item_to_find}: {raw_result}"
                    
                    # Save options
                    if state is not None:
                        if "options" not in state or not isinstance(state["options"], list):
                            state["options"] = []
                        state["options"].append(f"{item_to_find}: {raw_result}")
                        state.setdefault("supplier_options", {})[item_to_find] = _parse_supplier_options(raw_result)

                # --- TOOL C: PLACE ORDER ---
                elif func_name == "place_order":
                    item = args.get("item_name")
                    qty = args.get("quantity")
                    supplier = args.get("supplier_info")
                    cost = args.get("cost_per_unit")
                    supplier_details = {}
                    staged_items = {
                        order.get("item_name")
                        for order in state.get("pending_orders", [])
                    } if state else set()

                    if item in staged_items:
                        print(f"      ⏭️ SKIPPING DUPLICATE STAGED ORDER: {item}")
                        result = f"SKIPPED: {item} has already been staged in this session."
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool.id,
                            "content": str(result)
                        })
                        continue

                    if item:
                        if not isinstance(qty, int) or qty <= 0:
                            qty = _resolve_order_quantity(item, state)
                            print(f"      📦 RESOLVED ORDER QUANTITY: {item} -> {qty}")

                        if not supplier or float(cost or 0) <= 0:
                            supplier_details = _resolve_supplier(item, state)
                            supplier = supplier_details.get("supplier", "")
                            cost = supplier_details.get("cost_per_unit", 0.0)
                            print(f"      🏷️ RESOLVED SUPPLIER: {item} -> {supplier} @ £{cost}")
                        else:
                            supplier_details = {
                                "supplier": supplier,
                                "cost_per_unit": float(cost),
                                "delivery": "",
                                "contact_email": "",
                                "contact_phone": "",
                            }
                    
                    # Stage order for approval and downstream communication.
                    try:
                        total = float(qty) * float(cost)
                        if state.get("total_spent") is None: state["total_spent"] = 0
                        state["total_spent"] += total
                        
                        stock_details = state.get("stock_details", {}).get(item, {})
                        location = stock_details.get("location", "")

                        order_line = {
                            "item_name": item,
                            "supplier": supplier,
                            "quantity": qty,
                            "cost_per_unit": float(cost),
                            "total_cost": total,
                            "location": location,
                            "delivery": supplier_details.get("delivery", ""),
                            "contact_email": supplier_details.get("contact_email", ""),
                            "contact_phone": supplier_details.get("contact_phone", ""),
                        }

                        if "pending_orders" not in state:
                            state["pending_orders"] = []
                        state["pending_orders"].append(order_line)

                        if "receipt" not in state: state["receipt"] = []
                        state["receipt"].append([item, supplier, qty, f"£{cost}", f"£{total}"])
                        
                        print(f"      🧾 STAGING ORDER: {qty}x {item} from {supplier} (Total: £{total})")
                    except:
                        print("      ⚠️ Cost calculation error")

                    result = (
                        f"STAGED: {qty} x {item} from {supplier} at £{cost} each. "
                        f"Pending email confirmation before inventory update."
                    )
                    if state is not None:
                        state["order_confirmed"] = True

                else:
                    result = f"Tool {func_name} executed (Simulation)"

                # IMPORTANT: Append the result to history
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool.id,
                    "content": str(result)
                })

            if state is not None and state.get("human_approval"):
                shortages = set(state.get("shortages", []))
                staged = {
                    order.get("item_name")
                    for order in state.get("pending_orders", [])
                }
                if shortages and shortages.issubset(staged):
                    return _format_order_summary(state)
    
    # Required for the Manager to treat this agent as a tool
    def as_tool(self, tool_name, tool_description):
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The task or question."
                        }
                    },
                    "required": ["query"]
                }
            }
        }
