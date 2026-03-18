import json
import os

ordered_items = set()

# --- ABSOLUTE PATH SETUP (Crucial for looking up IDs) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR) if "core" in BASE_DIR else BASE_DIR
INVENTORY_PATH = os.path.join(PROJECT_ROOT, "data", "inventory.json")

def get_supplier(item_name: str, file_path_supplier: str) -> str:
    
    """
    Finds suppliers for a given item name.
    1. Looks up the Item ID from inventory.json using the name.
    2. Searches suppliers.json for that ID.
    """

     # Debug: Print where we are looking
    print(f"📂 DEBUG: Procurement looking for '{item_name}'...")

    target_id = None

    try:
        with open(INVENTORY_PATH, 'r', encoding='utf-8-sig') as f:
            inventory = json.load(f)
            for item in inventory:
                name_in_file = item.get("name", "").strip().lower()
                if name_in_file == item_name.strip().lower():
                    target_id = item.get("item_id")
                    print(f" MAPPING SUCCESS: '{item_name}' -> ID: '{target_id}'")
                    break
    except Exception as e:
        return f"Error reading inventory for ID lookup: {e}"
    
    try:
        with open(file_path_supplier, 'r', encoding='utf-8-sig') as f:
            suppliers = json.load(f)
    except FileNotFoundError:
        return "Error: Supplier file not found."

    available_suppliers = []

    for supplier in suppliers:
        
        costs = supplier.get("cost_per_unit", {})

        if target_id in costs:
            price = costs[target_id]
            is_approved = "Yes" if supplier.get("nhs_approved") else "No"

            available_suppliers.append({
                "supplier": supplier.get("name"),
                "cost": price,
                "delivery": f"{supplier.get('delivery_time_hours')} hrs",
                "nhs_approved": is_approved
            })

    if not available_suppliers:
        print(f" ID '{target_id}' found, but no suppliers sell it.")
        return "{}"

    print(f" FOUND {len(available_suppliers)} SUPPLIERS")
    return json.dumps(available_suppliers)