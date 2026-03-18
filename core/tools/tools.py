check_stock_tool_schema = {
    "type": "function",
    "function": {
        "name": "check_stock",
        "description": "Tool to check stock levels in the inventory.",
        "parameters": {
            "type": "object",  # <--- Essential
            "properties": {    # <--- Essential wrapper
                "file_path": {
                    "type": "string",
                    "description": "The path to the inventory JSON file."
                }
            },
            "required": ["file_path"]
        }
    }
}

get_supplier_tool_schema = {
    "type": "function",
    "function": {
        "name": "get_supplier",
        "description": "Tool to get NHS-approved suppliers for critical items.",
        "parameters": {
            "type": "object",  # <--- Essential
            "properties": {    # <--- Essential wrapper
                "item_name": {
                    "type": "string",
                    "description": "The name of the item to find suppliers for."
                },
                "file_path_supplier": {  # Make sure this matches your Python function argument name!
                    "type": "string",
                    "description": "The path to the suppliers JSON file."
                }
            },
            "required": ["item_name", "file_path_supplier"]
        }
    }
}

place_order_tool_schema = {
    "type": "function",         # 1. Top level needs type
    "function": {               # 2. EVERYTHING else goes inside this "function" key
        "name": "place_order",
        "description": "Tool to place orders for items from suppliers and update inventory.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "The name of the item to order."
                },
                "quantity": {
                    "type": "integer",
                    "description": "The quantity of the item to order."
                },
                "supplier_info": {
                    "type": "string",  # 3. CHANGED "set" to "string" (JSON doesn't have sets)
                    "description": "The name of the supplier to order from."
                },
                "cost_per_unit": {
                    "type": "number",  # 4. CHANGED "float" to "number" (JSON uses number for floats)
                    "description": "Cost per unit of the item."
                }
            },
            "required": ["item_name", "quantity", "supplier_info", "cost_per_unit"]
        }
    }
}
