import streamlit as st
from collections import defaultdict
from io import BytesIO
from urllib.parse import quote
import smtplib
import ssl
from email.message import EmailMessage

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

st.set_page_config(page_title="Simple Split Bill", layout="wide")

# ========== STATE ==========

if "initiator" not in st.session_state:
    st.session_state.initiator = {
        "name": "",
        "email": "",
        "accounts": [],  # list of {"label","detail"}
    }

if "items" not in st.session_state:
    # Use bracket access to avoid colliding with the SessionState.items() method
    st.session_state["items"] = {}  # {item: {"qty": float, "total_price": float}}

if "people" not in st.session_state:
    st.session_state.people = {}  # {name: {"email": str}}

if "shares" not in st.session_state:
    # shares[person][item] = qty
    st.session_state.shares = defaultdict(lambda: defaultdict(float))

if "tax" not in st.session_state:
    # total tax/service amount to split among payers
    st.session_state["tax"] = 0.0

if "restaurant" not in st.session_state:
    st.session_state["restaurant"] = {
        "name": "",
        "address": "",
        "phone": "",
    }


# ========== CORE LOGIC ==========

def add_payment_account(label, detail):
    label, detail = label.strip(), detail.strip()
    if label and detail:
        st.session_state.initiator["accounts"].append(
            {"label": label, "detail": detail}
        )


def add_item(name, qty, total_price):
    """Add or update an item.

    Returns a tuple (ok: bool, message: str). If ok is False, message is an error.
    If ok is True, message is an informational success message.
    """
    if not name:
        return False, "Item name is required."
    try:
        qty_f = float(qty)
        price_f = float(total_price)
    except Exception:
        return False, "Qty and Total Price must be numbers."

    if name in st.session_state["items"]:
        st.session_state["items"][name]["qty"] = qty_f
        st.session_state["items"][name]["total_price"] = price_f
        return True, f"Item '{name}' updated."

    st.session_state["items"][name] = {
        "qty": qty_f,
        "total_price": price_f,
    }
    return True, f"Item '{name}' added."


def add_person(name, email):
    if not name:
        return
    st.session_state.people[name] = {"email": email.strip()}
    _ = st.session_state.shares[name]  # ensure key exists


def unit_price(item):
    data = st.session_state["items"][item]
    return data["total_price"] / data["qty"] if data["qty"] else 0.0


def remaining_qty(item):
    used = sum(
        st.session_state.shares[p].get(item, 0)
        for p in st.session_state.shares
    )
    return st.session_state["items"][item]["qty"] - used


def assign_share(person, item, qty):
    if not person or not item:
        return "Select person & item."
    if item not in st.session_state["items"]:
        return f"Item '{item}' not found."
    qty = float(qty)
    if qty <= 0:
        return "Qty must be > 0."
    if qty > remaining_qty(item):
        return f"Not enough '{item}' left. Remaining: {remaining_qty(item)}"
    st.session_state.shares[person][item] += qty
    return None


def set_share(person, item, qty):
    """Set the assigned qty for (person, item) to qty (not additive).

    Validation: qty >= 0 and qty <= remaining_qty(item) + current_qty (so person can reduce or increase up to available).
    Returns an error message string on failure, or None on success.
    """
    if not person or not item:
        return "Select person & item."
    if item not in st.session_state["items"]:
        return f"Item '{item}' not found."
    try:
        qty_f = float(qty)
    except Exception:
        return "Qty must be a number."
    if qty_f < 0:
        return "Qty must be >= 0."
    current = st.session_state.shares[person].get(item, 0.0)
    available = remaining_qty(item) + current
    if qty_f > available:
        return f"Not enough '{item}' left. Available: {fmt_num(available)}"
    st.session_state.shares[person][item] = qty_f
    return None


def person_total(person):
    total = 0.0
    for item, qty in st.session_state.shares[person].items():
        total += qty * unit_price(item)
    return total


def person_breakdown(person):
    """Return a list of dicts describing what the person ordered and costs."""
    lines = []
    for item, qty in st.session_state.shares[person].items():
        if qty <= 0:
            continue
        up = unit_price(item)
        lines.append(
            {
                "item": item,
                "qty": qty,
                "unit": round(up, 2),
                "subtotal": round(qty * up, 2),
            }
        )
    return lines


def fmt_num(value):
    """Format numeric value with commas every 3 digits and drop trailing .00.

    Examples:
      7000 -> '7,000'
      7000.5 -> '7,000.5'
      7000.25 -> '7,000.25'
      7000.00 -> '7,000'
    Non-numeric values are returned as str(value).
    """
    try:
        v = float(value)
    except Exception:
        return str(value)
    s = f"{v:,.2f}"
    if s.endswith(".00"):
        return s[:-3]
    # strip trailing zeros like 7,000.50 -> 7,000.5
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def all_totals():
    # Compute subtotal per person, then split tax proportionally and return final totals
    subtotals = {
        p: round(person_total(p), 2)
        for p in st.session_state.people.keys()
        if any(st.session_state.shares[p].values())
    }
    total_sub = sum(subtotals.values())
    tax_total = float(st.session_state.get("tax", 0.0))
    totals = {}
    for p, sub in subtotals.items():
        tax_share = (sub / total_sub * tax_total) if total_sub > 0 else 0.0
        totals[p] = round(sub + tax_share, 2)
    return totals


def accounts_text():
    accs = st.session_state.initiator["accounts"]
    if not accs:
        return "Please pay to the initiator (account details to be provided)."
    lines = ["Please pay to one of these accounts:"]
    for a in accs:
        lines.append(f"- {a['label']}: {a['detail']}")
    return "\n".join(lines)


def build_email_body(person):
    total = round(person_total(person), 2)
    rest_lines = []
    rest = st.session_state.get("restaurant", {})
    if rest.get("name"):
        rest_lines.append(rest.get("name"))
    if rest.get("address"):
        rest_lines.append(rest.get("address"))
    if rest.get("phone"):
        rest_lines.append(f"Ph: {rest.get('phone')}")

    lines = rest_lines + [
        f"Hi {person},",
        "",
        "Here is your split bill summary:",
        "",
    ]

    for item, qty in st.session_state.shares[person].items():
        if qty > 0:
            up = unit_price(item)
            price = qty * up
            lines.append(f"- {item}: {fmt_num(qty)} x {fmt_num(up)} = {fmt_num(price)}")
    # Tax split
    subtotal = round(person_total(person), 2)
    total_all = sum(round(person_total(p), 2) for p in st.session_state.people.keys() if any(st.session_state.shares[p].values()))
    tax_total = float(st.session_state.get("tax", 0.0))
    tax_share = (subtotal / total_all * tax_total) if total_all > 0 else 0.0
    total_incl_tax = subtotal + tax_share

    lines += [
        "",
        f"Subtotal: {fmt_num(subtotal)}",
        f"Tax (your share): {fmt_num(tax_share)}",
        f"Total you should pay: {fmt_num(total_incl_tax)}",
        "",
        accounts_text(),
        "",
        "Thank you!",
    ]
    return "\n".join(lines)


def build_bill_image(totals):
    """
    Create a simple PNG summary:
    - Initiator info
    - Payment accounts
    - Person totals
    """
    initiator = st.session_state.initiator
    lines = []

    lines.append("Split Bill Summary")
    # Restaurant header (if provided)
    rest = st.session_state.get("restaurant", {})
    if rest.get("name"):
        lines.append(f"{rest.get('name')}")
    if rest.get("address"):
        lines.append(rest.get("address"))
    if rest.get("phone"):
        lines.append(f"Ph: {rest.get('phone')}")

    if initiator["name"] or initiator["email"]:
        lines.append(
            f"Initiator: {initiator['name']} ({initiator['email']})".strip()
        )

    if initiator["accounts"]:
        lines.append("")
        lines.append("Payment Accounts:")
        for acc in initiator["accounts"]:
            lines.append(f"- {acc['label']}: {acc['detail']}")

    lines.append("")
    lines.append("")
    lines.append("Details per person:")
    for person, total in totals.items():
        email = st.session_state.people.get(person, {}).get("email", "")
        header = f"{person} ({email})" if email else person
        lines.append(f"- {header}: {fmt_num(total)}")
        # List items for this person
        for item, qty in st.session_state.shares[person].items():
            if qty <= 0:
                continue
            up = unit_price(item)
            lines.append(f"    * {item}: {fmt_num(qty)} x {fmt_num(up)} = {fmt_num(qty * up)}")

    # Image layout
    width = 900
    line_height = 32
    padding = 30
    height = padding * 2 + line_height * len(lines)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
        font_bold = ImageFont.truetype("arialbd.ttf", 22)
    except:
        font = ImageFont.load_default()
        font_bold = font

    y = padding
    for i, line in enumerate(lines):
        f = font_bold if i == 0 else font
        draw.text((padding, y), line, fill="black", font=f)
        y += line_height

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ========== UI FLOW ==========

st.title("Simple Split Bill")

# --- Restaurant Info ---
st.header("🏷️ Restaurant Information")
col_r1, col_r2 = st.columns([3, 1])
with col_r1:
    st.session_state["restaurant"]["name"] = st.text_input(
        "Restaurant Name",
        value=st.session_state["restaurant"]["name"],
    )
with col_r2:
    st.session_state["restaurant"]["phone"] = st.text_input(
        "Phone",
        value=st.session_state["restaurant"]["phone"],
    )
st.session_state["restaurant"]["address"] = st.text_area(
    "Address / Notes",
    value=st.session_state["restaurant"]["address"],
)

# --- 1. Initiator Info ---
st.header("1️⃣ Initiator Information")

col_i1, col_i2 = st.columns(2)
with col_i1:
    st.session_state.initiator["name"] = st.text_input(
        "Initiator Name",
        value=st.session_state.initiator["name"],
    )
with col_i2:
    st.session_state.initiator["email"] = st.text_input(
        "Initiator Email",
        value=st.session_state.initiator["email"],
    )

st.markdown("**Payment Accounts** (e.g. BCA, DANA, GoPay)")

with st.form("add_account_form", clear_on_submit=True):
    acc_label = st.text_input("Account Label")
    acc_detail = st.text_input("Account Detail")
    if st.form_submit_button("Add Account"):
        add_payment_account(acc_label, acc_detail)

if st.session_state.initiator["accounts"]:
    st.table(st.session_state.initiator["accounts"])

st.markdown("---")

# --- 2. Bill Items ---
st.header("2️⃣ Bill Items")

with st.form("add_item_form", clear_on_submit=True):
    name = st.text_input("Item Name")
    qty = st.number_input("Qty", min_value=0.0, step=1.0)
    total_price = st.number_input("Total Price", min_value=0.0, step=1.0)
    if st.form_submit_button("Add / Update Item"):
        ok, msg = add_item(name, qty, total_price)
        if not ok:
            st.error(msg)
        else:
            st.success(msg)

if st.session_state["items"]:
    items_df = pd.DataFrame(
        [
            {
                "Item": n,
                "Qty": d["qty"],
                "Total": d["total_price"],
                "Unit": unit_price(n),
                "Remaining": remaining_qty(n),
            }
            for n, d in st.session_state["items"].items()
        ]
    )
    # Format numeric columns for display
    for col in ["Qty", "Total", "Unit", "Remaining"]:
        if col in items_df.columns:
            items_df[col] = items_df[col].apply(fmt_num)
    st.table(items_df)

st.markdown("---")

# --- 3. People ---
st.header("3️⃣ Add People")

with st.form("add_person_form", clear_on_submit=True):
    person_name = st.text_input("Person Name")
    person_email = st.text_input("Person Email (optional)")
    if st.form_submit_button("Add / Update Person"):
        add_person(person_name, person_email)

if st.session_state.people:
    st.table(
        [
            {"Person": n, "Email": d["email"]}
            for n, d in st.session_state.people.items()
        ]
    )

st.markdown("---")

# --- 4. Assign Items ---
st.header("4️⃣ Assign Items to People")

if st.session_state["items"] and st.session_state.people:
    with st.form("assign_form", clear_on_submit=True):
        person = st.selectbox(
            "Person", list(st.session_state.people.keys())
        )
        item = st.selectbox(
            "Item", list(st.session_state["items"].keys())
        )
        qty = st.number_input(
            "Qty taken (allow 0.5, etc.)",
            min_value=0.0,
            step=0.5,
        )
        if st.form_submit_button("Assign"):
            msg = assign_share(person, item, qty)
            if msg:
                st.error(msg)

    st.caption("Check remaining qty in the Bill Items table above.")
else:
    st.info("Add items and people first.")

# --- Editable current assignments per person ---
if st.session_state.people and st.session_state["items"]:
    st.markdown("---")
    st.header("4️⃣a Edit Current Assignments")
    st.markdown("Edit assigned quantities for each person. Set to 0 to remove an assignment.")
    for person in st.session_state.people.keys():
        with st.expander(f"Edit assignments — {person}"):
            email = st.session_state.people.get(person, {}).get("email", "")
            if email:
                st.write(f"Email: {email}")
            item_keys = list(st.session_state["items"].keys())
            # Render inputs for each item
            for item in item_keys:
                cur = st.session_state.shares[person].get(item, 0.0)
                key = f"edit_{person}_{item}".replace(" ", "_")
                # Initialize key with current value if not present
                if key not in st.session_state:
                    st.session_state[key] = float(cur)
                st.number_input(f"{item}", min_value=0.0, step=0.5, key=key)
            # Update button per person
            if st.button(f"Update {person}'s assignments", key=f"update_{person}"):
                errs = []
                for item in item_keys:
                    key = f"edit_{person}_{item}".replace(" ", "_")
                    newq = float(st.session_state.get(key, 0.0))
                    err = set_share(person, item, newq)
                    if err:
                        errs.append((item, err))
                if errs:
                    for it, e in errs:
                        st.error(f"{it}: {e}")
                else:
                    st.success(f"{person}'s assignments updated.")
                    # Clear temporary edit keys to reflect updated values next run
                    for item in item_keys:
                        key = f"edit_{person}_{item}".replace(" ", "_")
                        if key in st.session_state:
                            del st.session_state[key]

st.markdown("---")

# --- 5. Calculation + Email + Image Download ---
st.header("5️⃣ Calculation & Send")

# Tax input (total tax/service to split among payers)
st.session_state["tax"] = st.number_input(
    "Additional Tax / Service (total amount)", min_value=0.0, step=1.0, value=float(st.session_state.get("tax", 0.0))
)

totals = all_totals()

if totals:
    # Display totals
    st.subheader("Summary per Person")
    # Show a compact totals table
    # Build table with Subtotal, Tax share and Total
    rows = []
    # Precompute subtotals and total_sub
    subtotals = {
        p: round(person_total(p), 2)
        for p in st.session_state.people.keys()
        if any(st.session_state.shares[p].values())
    }
    total_sub = sum(subtotals.values())
    tax_total = float(st.session_state.get("tax", 0.0))
    for p, total in totals.items():
        sub = subtotals.get(p, 0.0)
        tax_share = (sub / total_sub * tax_total) if total_sub > 0 else 0.0
        rows.append(
            {
                "Person": p,
                "Email": st.session_state.people.get(p, {}).get("email", ""),
                "Subtotal": sub,
                "Tax": tax_share,
                "Total": total,
            }
        )
    df_totals = pd.DataFrame(rows)
    # Format numeric columns
    for col in ["Subtotal", "Tax", "Total"]:
        if col in df_totals.columns:
            df_totals[col] = df_totals[col].apply(fmt_num)
    st.table(df_totals)

    # More informative per-person breakdowns
    for p, total in totals.items():
        with st.expander(f"{p} — {fmt_num(total)}"):
            email = st.session_state.people.get(p, {}).get("email", "")
            if email:
                st.write(f"Email: {email}")
            bd = person_breakdown(p)
            if bd:
                df_bd = pd.DataFrame(bd)
                # Format numeric columns
                for col in ["qty", "unit", "subtotal"]:
                    if col in df_bd.columns:
                        df_bd[col] = df_bd[col].apply(fmt_num)
                st.table(df_bd)
            else:
                st.write("No items assigned.")

    # Show payment accounts prominently
    st.markdown("**Payment Accounts / Where to send payment**")
    st.text(accounts_text())

    # Email sending options
    st.subheader("Send via Email")
    st.markdown("You can either open an email draft (your mail client) or send directly from this app via SMTP.")
    # mailto links (keep as alternative)
    with st.expander("Open email draft in your email client (mailto)"):
        for person, total in totals.items():
            email = st.session_state.people.get(person, {}).get("email", "")
            if not email:
                continue
            body = build_email_body(person)
            # include restaurant name in subject if provided
            rest_name = st.session_state.get("restaurant", {}).get("name", "")
            subject = f"Split Bill Summary{(': ' + rest_name) if rest_name else ''}"
            mailto = (
                f"mailto:{email}"
                f"?subject={quote(subject)}"
                f"&body={quote(body)}"
            )
            st.markdown(
                f"- [{person} - open email draft]({mailto})",
                unsafe_allow_html=True,
            )

    # Download summary as image
    img_buf = build_bill_image(totals)
    st.subheader("Download Bill as Image")
    st.download_button(
        label="📥 Download Summary PNG",
        data=img_buf,
        file_name="split_bill_summary.png",
        mime="image/png",
    )

else:
    st.info("No assignments yet. Assign items to see totals.")

# --- Reset button ---
if st.button("Reset All Data"):
    st.session_state.initiator = {
        "name": "",
        "email": "",
        "accounts": [],
    }
    st.session_state["items"] = {}
    st.session_state.people = {}
    st.session_state.shares = defaultdict(lambda: defaultdict(float))
    st.experimental_rerun()
