from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image


DEFAULT_PACKAGE_DIR = Path("models") / "openmv_classifier"
DEFAULT_SPLIT_DIR = Path("reports") / "splits"


def load_tf():
    import tensorflow as tf

    return tf


def build_keras_model(tf, input_size: int, num_classes: int):
    inputs = tf.keras.Input(shape=(input_size, input_size, 3), name="image")
    mean = tf.constant([0.485, 0.456, 0.406], dtype=tf.float32)
    std = tf.constant([0.229, 0.224, 0.225], dtype=tf.float32)
    x = tf.keras.layers.Lambda(
        lambda image: (tf.cast(image, tf.float32) / 255.0 - mean) / std,
        name="normalize",
    )(inputs)

    convs = []
    bns = []
    for filters in (16, 32, 64, 96):
        conv = tf.keras.layers.Conv2D(
            filters,
            kernel_size=3,
            padding="same",
            use_bias=False,
            name=f"conv_{filters}",
        )
        bn = tf.keras.layers.BatchNormalization(epsilon=1e-5, name=f"bn_{filters}")
        x = conv(x)
        x = bn(x, training=False)
        x = tf.keras.layers.ReLU(name=f"relu_{filters}")(x)
        if filters != 96:
            x = tf.keras.layers.MaxPooling2D(pool_size=2, strides=2, name=f"pool_{filters}")(x)
        else:
            x = tf.keras.layers.GlobalAveragePooling2D(name="global_avg_pool")(x)
        convs.append(conv)
        bns.append(bn)

    outputs = tf.keras.layers.Dense(num_classes, name="classifier")(x)
    model = tf.keras.Model(inputs=inputs, outputs=outputs, name="smartcar_classifier")
    return model, convs, bns, model.get_layer("classifier")


def set_weights(model_parts, weights: np.lib.npyio.NpzFile) -> None:
    _, convs, bns, dense = model_parts
    conv_keys = ["features.0", "features.4", "features.8", "features.12"]
    bn_keys = ["features.1", "features.5", "features.9", "features.13"]

    for conv, key in zip(convs, conv_keys):
        # PyTorch: out, in, h, w. Keras: h, w, in, out.
        conv_weight = np.transpose(weights[f"{key}.weight"], (2, 3, 1, 0))
        conv.set_weights([conv_weight])

    for bn, key in zip(bns, bn_keys):
        bn.set_weights(
            [
                weights[f"{key}.weight"],
                weights[f"{key}.bias"],
                weights[f"{key}.running_mean"],
                weights[f"{key}.running_var"],
            ]
        )

    dense.set_weights(
        [
            np.transpose(weights["classifier.2.weight"], (1, 0)),
            weights["classifier.2.bias"],
        ]
    )


def read_split_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_image(path: Path, input_size: int) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("RGB").resize((input_size, input_size), Image.BILINEAR)
        return np.asarray(image, dtype=np.float32)


def representative_dataset(rows: list[dict[str, str]], input_size: int, limit: int):
    root = Path.cwd()
    for row in rows[:limit]:
        path = Path(row["path"])
        if not path.is_absolute():
            path = root / path
        image = load_image(path, input_size)
        yield [np.expand_dims(image, axis=0)]


def evaluate_keras(model, rows: list[dict[str, str]], input_size: int, limit: int = 0) -> float:
    root = Path.cwd()
    total = 0
    correct = 0
    selected = rows[:limit] if limit > 0 else rows
    for row in selected:
        path = Path(row["path"])
        if not path.is_absolute():
            path = root / path
        image = np.expand_dims(load_image(path, input_size), axis=0)
        logits = model(image, training=False).numpy()[0]
        prediction = int(np.argmax(logits))
        target = int(row["label_id"])
        total += 1
        correct += int(prediction == target)
    return correct / max(1, total)


def evaluate_tflite(tf, model_path: Path, rows: list[dict[str, str]], input_size: int, limit: int = 0) -> float:
    root = Path.cwd()
    interpreter = tf.lite.Interpreter(model_path=str(model_path))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    input_index = input_details["index"]
    output_index = output_details["index"]
    input_dtype = input_details["dtype"]
    input_scale, input_zero_point = input_details["quantization"]

    total = 0
    correct = 0
    selected = rows[:limit] if limit > 0 else rows
    for row in selected:
        path = Path(row["path"])
        if not path.is_absolute():
            path = root / path
        image = np.expand_dims(load_image(path, input_size), axis=0)
        if np.issubdtype(input_dtype, np.integer):
            image = np.round(image / input_scale + input_zero_point)
            image = np.clip(image, np.iinfo(input_dtype).min, np.iinfo(input_dtype).max).astype(input_dtype)
        else:
            image = image.astype(input_dtype)

        interpreter.set_tensor(input_index, image)
        interpreter.invoke()
        output = interpreter.get_tensor(output_index)[0]
        prediction = int(np.argmax(output))
        target = int(row["label_id"])
        total += 1
        correct += int(prediction == target)
    return correct / max(1, total)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert the trained PyTorch-weight classifier to TFLite.")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR)
    parser.add_argument("--split-dir", type=Path, default=DEFAULT_SPLIT_DIR)
    parser.add_argument("--representative-limit", type=int, default=512)
    parser.add_argument("--eval-limit", type=int, default=0)
    args = parser.parse_args()

    tf = load_tf()
    package_dir = args.package_dir
    weights = np.load(package_dir / "classifier_v3_weights_np.npz")
    label_map = json.loads((package_dir / "label_map.json").read_text(encoding="utf-8"))
    input_size = int(weights["__input_size__"][0])
    num_classes = len(label_map)

    model_parts = build_keras_model(tf, input_size=input_size, num_classes=num_classes)
    model = model_parts[0]
    # Build variables before assigning weights.
    model(np.zeros((1, input_size, input_size, 3), dtype=np.float32), training=False)
    set_weights(model_parts, weights)

    test_rows = read_split_rows(args.split_dir / "test.csv")
    train_rows = read_split_rows(args.split_dir / "train.csv")
    keras_acc = evaluate_keras(model, test_rows, input_size, args.eval_limit)

    saved_model_dir = package_dir / "keras_saved_model"
    if saved_model_dir.exists():
        shutil.rmtree(saved_model_dir)
    model.export(saved_model_dir)

    float_converter = tf.lite.TFLiteConverter.from_saved_model(str(saved_model_dir))
    float_tflite = float_converter.convert()
    float_path = package_dir / "classifier_float.tflite"
    float_path.write_bytes(float_tflite)

    int8_converter = tf.lite.TFLiteConverter.from_saved_model(str(saved_model_dir))
    int8_converter.optimizations = [tf.lite.Optimize.DEFAULT]
    int8_converter.representative_dataset = lambda: representative_dataset(
        train_rows,
        input_size,
        args.representative_limit,
    )
    int8_converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    int8_converter.inference_input_type = tf.uint8
    int8_converter.inference_output_type = tf.uint8
    int8_tflite = int8_converter.convert()
    int8_path = package_dir / "classifier_int8.tflite"
    int8_path.write_bytes(int8_tflite)
    deploy_path = package_dir / "classifier.tflite"
    deploy_path.write_bytes(int8_tflite)

    float_acc = evaluate_tflite(tf, float_path, test_rows, input_size, args.eval_limit)
    int8_acc = evaluate_tflite(tf, int8_path, test_rows, input_size, args.eval_limit)

    report = {
        "input_size": input_size,
        "num_classes": num_classes,
        "keras_test_acc": keras_acc,
        "float_tflite_test_acc": float_acc,
        "int8_tflite_test_acc": int8_acc,
        "representative_limit": args.representative_limit,
        "eval_limit": args.eval_limit,
        "files": {
            "float_tflite": str(float_path),
            "int8_tflite": str(int8_path),
            "deploy_tflite": str(deploy_path),
        },
    }
    (package_dir / "tflite_conversion_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
