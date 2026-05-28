from pathlib import Path

import pandas as pd


WORKBOOKS = {
    "emperor": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\帝濠\帝濠酒店订单数据分析.xlsx"),
    "beverly": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\富豪\富豪酒店订单数据分析.xlsx"),
    "riviera": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\濠璟\濠璟酒店订单数据分析.xlsx"),
    "kyoto": Path(r"D:\Meng's Workspace\酒店自营包销数据分析\京都酒店订单数据分析.xlsx"),
}


def main() -> None:
    for hotel_id, path in WORKBOOKS.items():
        workbook = pd.ExcelFile(path)
        print(f"--- {hotel_id}: {path}")
        print(f"sheets: {workbook.sheet_names}")
        orders = pd.read_excel(path, sheet_name="订单数据", nrows=5)
        print(f"sample shape: {orders.shape}")
        print(f"columns: {list(orders.columns)}")
        print(orders.head(2).to_string(index=False))


if __name__ == "__main__":
    main()
