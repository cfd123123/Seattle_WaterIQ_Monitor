"""
离线训练脚本：从指定 CSV 读取与线上一致的 11 项数值特征与 Pollution_Level 标签，
训练随机森林分类器，保存 water_model.pkl 与 label_encoder.pkl，供 main.py 加载推理。

CSV 需包含列：Water_Temperature_C、pH、Dissolved_Oxygen_mg_L、Conductivity_uS_cm、
Turbidity_NTU、Nitrate_mg_L、Ammonia_N_mg_L、Total_Phosphorus_mg_L、COD_mg_L、
BOD_mg_L、Heavy_Metals_Pb_ug_L、Pollution_Level。

用法示例：
  .venv/bin/python train_water_model.py --input path/to/training.csv
"""
import argparse

from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
import joblib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="训练水质污染等级模型")
    parser.add_argument(
        "--input",
        required=True,
        help="训练输入 CSV 路径（须含 11 项特征列与 Pollution_Level）",
    )
    parser.add_argument(
        "--model-out",
        default="water_model.pkl",
        help="模型输出路径（默认 water_model.pkl）",
    )
    parser.add_argument(
        "--encoder-out",
        default="label_encoder.pkl",
        help="编码器输出路径（默认 label_encoder.pkl）",
    )
    return parser.parse_args()


def main() -> None:
    """
    训练主流程（脚本入口）：

    1. 读入水质 CSV；
    2. 取出与线上一致的 11 列特征；
    3. 对 Pollution_Level 做 LabelEncoder；
    4. 划分训练/测试集并拟合 RandomForestClassifier；
    5. 在测试集上打印准确率与 classification_report；
    6. 将模型与编码器序列化到当前目录，供 FastAPI 服务加载。
    """
    args = parse_args()
    input_path = Path(args.input)
    model_out = Path(args.model_out)
    encoder_out = Path(args.encoder_out)

    # 1) 加载数据
    df = pd.read_csv(input_path)

    # 2) 特征选择（仅使用数值监测指标）
    features = [
        "Water_Temperature_C",
        "pH",
        "Dissolved_Oxygen_mg_L",
        "Conductivity_uS_cm",
        "Turbidity_NTU",
        "Nitrate_mg_L",
        "Ammonia_N_mg_L",
        "Total_Phosphorus_mg_L",
        "COD_mg_L",
        "BOD_mg_L",
        "Heavy_Metals_Pb_ug_L",
    ]
    X = df[features]

    # 3) 标签编码：将字符串类别转为 0..K-1，与 sklearn 分类器接口一致
    le = LabelEncoder()
    y = le.fit_transform(df["Pollution_Level"])

    # 4) 训练/测试切分（stratify 保持各类比例）并训练模型
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(X_train, y_train)

    # 5) 基础评估：准确率 + 按类别的 precision/recall 等
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Test Accuracy: {acc:.4f}")
    print("Classification Report:")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # 6) 保存模型和标签编码器（推理时需用同一套 encoder 做 inverse_transform）
    joblib.dump(model, model_out)
    joblib.dump(le, encoder_out)
    print(f"Input CSV: {input_path}")
    print(f"Model saved: {model_out}")
    print(f"Encoder saved: {encoder_out}")


if __name__ == "__main__":
    main()
