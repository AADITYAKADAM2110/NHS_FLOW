import json
import os
from datetime import datetime

# --- ABSOLUTE PATH SETUP ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR) if "core" in BASE_DIR else BASE_DIR
INVENTORY_PATH = os.path.join(PROJECT_ROOT, "data", "inventory.json")

def place_order(item_name, quantity, supplier_info, cost_per_unit):
    """
    Places an order and ACTUALLY updates the inventory.json file.
    """
    print(f"      💾 UPDATING INVENTORY: Adding {quantity} to '{item_name}'...")

    try:
        # 1. Read the file
        with open(INVENTORY_PATH, 'r', encoding='utf-8-sig') as f:
            inventory = json.load(f)
        
        item_found = False
        
        # 2. Update the specific item
        for item in inventory:
            # Flexible Name Matching
            db_name = item.get("name", "").strip().lower()
            target_name = item_name.strip().lower()
            
            if db_name == target_name:
                # UPDATE THE NUMBERS
                current = int(item.get("current_stock", 0))
                new_stock = current + int(quantity)
                
                item["current_stock"] = new_stock
                item["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                print(f"      ✅ STOCK WILL BE UPDATED: {current} -> {new_stock}")
                item_found = True
                break
        
        if not item_found:
            return f"Error: Item '{item_name}' not found in inventory file."

        # 3. Save the file back to disk
        with open(INVENTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(inventory, f, indent=4)
            
        return f"SUCCESS: Ordered {quantity} x {item_name} from {supplier_info}. New Stock Level will be: {new_stock}"

    except Exception as e:
        return f"Error updating inventory file: {e}"