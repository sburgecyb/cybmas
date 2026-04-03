import json

# Input / Output file paths
input_file = "l3_final_dataset.json"
output_file = "l3_ordered_dataset.json"

# Load JSON
with open(input_file, "r") as f:
    data = json.load(f)

tickets = data.get("tickets", [])
incidents = data.get("incidents", [])

b1 = [t for t in tickets if t.get("ticket_type") in ["Task","Story", "Bug"] and t.get("business_unit") == "B1"]
b2 = [t for t in tickets if t.get("ticket_type") in ["Task","Story", "Bug"] and t.get("business_unit") == "B2"]


tickets_sorted = b1 + b2 

# Sort tickets by business_unit (B1 first, then B2)


# Final structure (tickets first, then incidents)
ordered_data = {
    "tickets": tickets_sorted,
    "incidents": incidents
}

# Save output
with open(output_file, "w") as f:
    json.dump(ordered_data, f, indent=2)

print(f"Ordered dataset written to {output_file}")