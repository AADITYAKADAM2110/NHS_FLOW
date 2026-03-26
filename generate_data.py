import json
import os
import random
from datetime import datetime

from core.realtime.state import build_realtime_state, save_realtime_state


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "core", "data")
NUM_ITEMS = 50
SIMULATION_START = datetime(2026, 4, 1, 6, 0)


categories = {
    "PPE": ["Gloves", "Gown", "Face Shield", "Shoe Covers", "Apron", "Surgical Mask"],
    "Medication": ["Amoxicillin", "Ibuprofen", "Insulin", "Metformin", "Atorvastatin", "Paracetamol"],
    "Equipment": ["Syringe 5ml", "Cannula 18G", "Bandage", "Gauze", "Scalpel", "Thermometer"],
    "Critical": ["N95 Respirator Mask", "Paracetamol IV 10mg"],
}


suppliers_list = [
    {"name": "MedSupply Co (Manchester)", "nhs": True, "speed": 24, "markup": 1.0, "carbon": "Medium"},
    {"name": "GreenHealth Logistics (London)", "nhs": True, "speed": 4, "markup": 1.2, "carbon": "Low"},
    {"name": "BudgetMedical Global (Overseas)", "nhs": False, "speed": 72, "markup": 0.6, "carbon": "High"},
    {"name": "RapidResponse York", "nhs": True, "speed": 12, "markup": 1.1, "carbon": "Medium"},
    {"name": "Global Pharma Corp", "nhs": False, "speed": 48, "markup": 0.8, "carbon": "High"},
]


ward_profiles = [
    {
        "ward_id": "WARD-ICU-01",
        "ward": "ICU",
        "capacity": 24,
        "occupied_beds": 18,
        "ventilators_available": 10,
        "monitors_available": 18,
        "acuity": "Critical",
    },
    {
        "ward_id": "WARD-EMR-01",
        "ward": "Emergency",
        "capacity": 32,
        "occupied_beds": 24,
        "ventilators_available": 4,
        "monitors_available": 16,
        "acuity": "High",
    },
    {
        "ward_id": "WARD-GEN-01",
        "ward": "General",
        "capacity": 60,
        "occupied_beds": 38,
        "ventilators_available": 2,
        "monitors_available": 20,
        "acuity": "Medium",
    },
    {
        "ward_id": "WARD-SUR-01",
        "ward": "Surgery",
        "capacity": 28,
        "occupied_beds": 19,
        "ventilators_available": 6,
        "monitors_available": 14,
        "acuity": "High",
    },
    {
        "ward_id": "WARD-MAT-01",
        "ward": "Maternity",
        "capacity": 22,
        "occupied_beds": 14,
        "ventilators_available": 1,
        "monitors_available": 10,
        "acuity": "Medium",
    },
]


def required_resources(occupancy):
    return {
        "required_nurses": max(2, -(-occupancy // 4)),
        "required_doctors": max(1, -(-occupancy // 12)),
        "required_ventilators": -(-int(occupancy * 18) // 100),
        "required_monitors": -(-int(occupancy * 45) // 100),
    }


def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def generate_inventory_and_suppliers():
    inventory = []
    supplier_catalog = []

    print("Generating suppliers catalog...")
    for sup in suppliers_list:
        clean_name = sup["name"].replace(" ", "").replace("(", "").replace(")", "").lower()
        supplier_catalog.append(
            {
                "supplier_id": f"SUP-{sup['name'][:3].upper()}-{random.randint(10, 99)}",
                "name": sup["name"],
                "nhs_approved": sup["nhs"],
                "delivery_time_hours": sup["speed"],
                "cost_per_unit": {},
                "carbon_footprint": sup["carbon"],
                "contact": {
                    "email": f"sales@{clean_name[:15]}.com",
                    "phone": f"+44 {random.randint(7000, 7999)} {random.randint(100000, 999999)}",
                },
            }
        )

    print(f"Generating {NUM_ITEMS} inventory items...")
    all_item_names = categories["Critical"][:]
    while len(all_item_names) < NUM_ITEMS:
        cat_key = random.choice(["PPE", "Medication", "Equipment"])
        base_name = random.choice(categories[cat_key])
        suffix = random.choice(["(Size S)", "(Size M)", "(Size L)", "Type A", "Type B", "Generic", "Pack"])
        new_name = f"{base_name} {suffix}"
        if new_name not in all_item_names:
            all_item_names.append(new_name)

    for name in all_item_names:
        if "Paracetamol" in name or "Ibuprofen" in name or "Insulin" in name:
            cat_prefix = "MED"
            cat_full = "Medication"
        elif "Syringe" in name or "Scalpel" in name:
            cat_prefix = "EQP"
            cat_full = "Equipment"
        else:
            cat_prefix = "PPE"
            cat_full = "PPE"

        item_id = f"{cat_prefix}-{name.split()[0].upper()[:4]}-{random.randint(100, 999)}"
        if random.random() < 0.3:
            min_thresh = random.randint(50, 100)
            current = random.randint(0, 20)
        else:
            min_thresh = random.randint(20, 50)
            current = random.randint(60, 200)

        inventory.append(
            {
                "item_id": item_id,
                "name": name,
                "category": cat_full,
                "location": f"Zone {random.choice(['A', 'B', 'C', 'ICU', 'Pharmacy'])}",
                "current_stock": current,
                "min_threshold": min_thresh,
                "unit": "box" if cat_prefix == "PPE" else "vial" if cat_prefix == "MED" else "pack",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

        base_price = round(random.uniform(2.0, 45.0), 2)
        for sup_data, sup_obj in zip(suppliers_list, supplier_catalog):
            price = round(base_price * sup_data["markup"] * random.uniform(0.95, 1.05), 2)
            if random.random() < 0.8:
                sup_obj["cost_per_unit"][item_id] = price

    return inventory, supplier_catalog


def generate_staff_dataset():
    roles = [
        ("Nurse", "Band 5"),
        ("Nurse", "Band 6"),
        ("Doctor", "Registrar"),
        ("Doctor", "Consultant"),
        ("Support", "HCA"),
    ]
    staff = []
    for ward in ward_profiles:
        for index in range(random.randint(8, 14)):
            role, band = random.choice(roles)
            staff.append(
                {
                    "staff_id": f"STF-{ward['ward'][:3].upper()}-{index + 1:03d}",
                    "name": f"{ward['ward']} Staff {index + 1}",
                    "ward": ward["ward"],
                    "role": role,
                    "band": band,
                    "shift": random.choice(["Day", "Night", "On-call"]),
                    "status": random.choice(["On duty", "Break", "Available"]),
                    "hours_remaining": random.randint(2, 12),
                    "last_updated": SIMULATION_START.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    return staff


def write_json(filename, payload):
    with open(os.path.join(DATA_DIR, filename), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)


def generate_datasets():
    ensure_data_dir()

    inventory, suppliers = generate_inventory_and_suppliers()
    staff_dataset = generate_staff_dataset()

    write_json("inventory.json", inventory)
    write_json("suppliers.json", suppliers)
    write_json("staff.json", staff_dataset)
    save_realtime_state(build_realtime_state(now=SIMULATION_START, mode="simulation"))

    print("Generated datasets:")
    print(f"  - inventory.json ({len(inventory)} rows)")
    print(f"  - suppliers.json ({len(suppliers)} rows)")
    print(f"  - staff.json ({len(staff_dataset)} rows)")
    print("  - realtime_state.json (1 state file)")


if __name__ == "__main__":
    generate_datasets()
