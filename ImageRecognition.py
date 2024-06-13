import torch
import easyocr
import random
import io
from PIL import Image
from collections import Counter
import hashlib
import requests
import base64
import numpy as np
import json
from Shared_vars import blipcache, config, uploads
from transformers import AutoModelForCausalLM, CodeGenTokenizerFast as Tokenizer
from PIL import Image

if config.enabled_features["image_input"]["backend"] == "moondream":
    model_id = "vikhyatk/moondream2"
    model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True, revision="2024-04-02")
    tokenizer = Tokenizer.from_pretrained(model_id)


yolo = torch.hub.load("ultralytics/yolov5", "yolov5m")
reader = easyocr.Reader(["en"])


def llamacpp_img(raw_image):
    # Convert raw image to base64 encoding
    prebuf = io.BytesIO()
    raw_image.save(prebuf, format="PNG")
    raw_image = base64.b64encode(prebuf.getvalue()).decode("utf-8")
    content = ""

    # Define the API endpoint URL
    url = config.enabled_features["image_input"]["URI"]

    # Define the prompt
    prompt = "[img-0]"

    # Define the parameters
    params = {
        "prompt": [prompt],
        "temperature": 0.1,
        "min_p": 0.05,
        "n_predict": 150,
        "stream": True,
        "seed": -1,
        "image_data": [{"data": raw_image, "id": 0}],
    }

    request = requests.post(url, json=params)
    for line in request.iter_lines(decode_unicode=True):
        try:
            if "data" in line:
                print(
                    json.loads("".join(line.split("data:")[1:]))["content"],
                    end="",
                    flush=True,
                )
                content += json.loads("".join(line.split("data:")[1:]))["content"]

        except Exception as e:
            print(e)
    return content

def find_center(bounding_box):
    x_min, y_min = bounding_box[0][0], bounding_box[0][1]
    x_max, y_max = bounding_box[2][0], bounding_box[2][1]

    center_x = (x_min + x_max) / 2
    center_y = (y_min + y_max) / 2

    return (center_x, center_y)


def remove_duplicates(data):  # ft. airoboros-l2-70b
    """
    This function removes duplicates from a list and returns a new list with the count of each element.

    Args:
      data: A list of strings.

    Returns:
      A list of strings with the count of each element.
    """
    # Create a dictionary to store the count of each element.
    counts = Counter(data)

    # Create a new list to store the results.
    results = []

    # Loop through each element in the dictionary.
    for key, value in counts.items():
        # If the count is greater than 1, add the element to the results list with the count.
        if value > 1:
            results.append(f"{value}x {key}")
        # If the count is 1, add the element to the results list without the count.
        else:
            results.append(key)

    return results


def decode_img(msg):
    msg = base64.b64decode(msg)
    buf = io.BytesIO(msg)
    img = Image.open(buf)
    return img


def find_midpoint(ymin, ymax, xmin, xmax):
    middle_x = (xmax + xmin) / 2
    middle_y = (ymax + ymin) / 2
    return f'Position: {middle_x}, {middle_y}'


def identify(input):
    imageoutput = ""
    ocrTranscription = ""
    ocrTranscriptionT = ""
    foundobjt = ""
    foundobj = ""
    raw_image = ""

    raw_image = decode_img(input)
    width = raw_image.width
    height = raw_image.height

    out = ""
    avgimg = raw_image.resize((10, 10), Image.LANCZOS).convert("L")
    pixel_data = list(avgimg.getdata())
    avg_pixel = sum(pixel_data) / len(pixel_data)
    raw_image = raw_image.convert("RGB")
    ocrresult = reader.readtext(np.array(raw_image), paragraph=True)
    ocrTranscription = '"'
    yoloresults = yolo(np.array(raw_image))
    tempres = []
    
    for x in json.loads(yoloresults.pandas().xyxy[0].to_json(orient="records")):
        if x["confidence"] > 0.4:
            print(f"Confidence: {x['confidence']}, {x['name']}")
            tempres.append(f"{x['name']}, {find_midpoint(x['ymin'],x['ymax'],x['xmin'],x['xmax'])}")
    tempres = remove_duplicates(tempres)
    foundobjt = ",".join(tempres)
    if not foundobjt == "":
        foundobj = "Object recognition: " + foundobjt
    for x in ocrresult:
        position = find_center(x[0])
        ocrTranscriptionT += f"'{x[1]}' Position: {position}." + "\n"
    if not ocrTranscriptionT == "":
        ocrTranscription = "OCR Output: " + ocrTranscriptionT
    ocrTranscription = ocrTranscription.strip()
    ocrTranscription += '"'
    print(ocrTranscription)
    bits = "".join(["1" if (px >= avg_pixel) else "0" for px in pixel_data])
    hex_representation = str(hex(int(bits, 2)))[2:][::-1].upper()
    sha = hashlib.sha1(hex_representation.encode()).hexdigest()
    if sha in blipcache:
        out = blipcache[sha]
    else:
        if config.enabled_features["image_input"]["backend"] != "moondream":
            out = llamacpp_img(raw_image)
            print(out)
        else:
            enc_image = model.encode_image(raw_image)
            out = model.answer_question(enc_image, "Describe this image.", tokenizer)
            print(out)
        blipcache[sha] = out
    imageoutput = out
    ID = random.randrange(76, 25859, 5)
    while ID in uploads:
        ID = random.randrange(76, 25859, 5)
    uploads[f"{ID}"] = input
    print(f"Image ID: {ID}")
    return f" <image>Description: {imageoutput}; {ocrTranscription}; {foundobj}; ID: {ID}</image>"
