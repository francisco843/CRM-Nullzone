# Addons

All `.py` files in this folder run when the web server starts.

## Practical rules

- They run in alphabetical order.
- You can use top-level code, `if __name__ == "__main__":`, `run(context)`, `main(context)`, or `main()`.
- If a script modifies data, make it idempotent.
- Results are shown on the dashboard.
- Keep manual utilities out of this folder. Put them in `tools/` so startup stays deterministic.

## Available context

- `project_root`
- `db_path`
- `query_all`
- `query_one`
- `execute`
- `executemany`
- `get_setting`
- `set_setting`
- `register_activity`
- `log`
