import json


def check_stock(file_path):

    """Tool to check stock levels in the inventory."""
    
    # Debug: Print where we are looking
    print(f"📂 DEBUG: Reading file from: {file_path}")

    try:
        # 'utf-8-sig' automatically handles the hidden BOM characters from Windows Notepad
        with open(file_path, 'r', encoding='utf-8-sig') as file:
            inventory = json.load(file)
    except FileNotFoundError:
        return f"Error: Inventory file not found at {file_path}"
    except json.JSONDecodeError:
        return "Error: Invalid JSON format."
    
    inventory_status = {}
    
    for item in inventory:
        item_name = item.get('name', 'Unknown Item')
        quantity = item.get('current_stock', 0)
        critical_threshold = item.get('min_threshold', 0)
        
        if quantity <= critical_threshold:
            status = "CRITICAL"
        else:
            status = "Sufficient"
        
        inventory_status[item_name] = {
            "name": item_name,
            "quantity": quantity,
            "critical_threshold": critical_threshold,
            "status": status,
            "location": item.get('location', '')
        }
    
    return json.dumps(inventory_status) # Return as JSON string for better readability, don't just print 
