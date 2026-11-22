
"""Configuration for each bank branch."""

# All cash values are stored in cents.
BRANCH_CONFIGS = {
    "A": {
        "cash": 5000000,
        "employees": 10,
        "minimum_reserve": 1000000
    },
    "B": {
        "cash": 3000000,
        "employees": 7,
        "minimum_reserve": 750000
    },
    "C": {
        "cash": 2000000,
        "employees": 5,
        "minimum_reserve": 500000
    }
}


def get_branch_config(branch_id):
    # Check whether the branch exists.
    if branch_id not in BRANCH_CONFIGS:
        raise ValueError(f"Unknown branch: {branch_id}")

    config = BRANCH_CONFIGS[branch_id].copy()

    # Check that all values are valid integers.
    for field in ("cash", "employees", "minimum_reserve"):
        if type(config[field]) is not int or config[field] < 0:
            raise ValueError(f"Invalid {field} for branch {branch_id}")

    # A branch must have enough cash for its minimum reserve.
    if config["cash"] < config["minimum_reserve"]:
        raise ValueError(
            f"Branch {branch_id} has insufficient starting cash"
        )

    return config
