import os
import json
from flask import Flask, render_template, request, jsonify
import boto3
from pymongo import MongoClient
from google import genai
from google.genai import types
from PIL import Image
import io

app = Flask(__name__)

# --- CONFIGURATIONS ---
MONGO_URI = os.environ.get("MONGO_URI", "")
DB_NAME = "property_database"
COLLECTION_NAME = "properties"

client_db = MongoClient(MONGO_URI)
db = client_db[DB_NAME]
collection = db[COLLECTION_NAME]

# AWS S3 Configurations
S3_BUCKET = (
    os.environ.get("AWS_S3_BUCKET") 
    or os.environ.get("S3_BUCKET") 
    or os.environ.get("AWS_S3_BUCKET_NAME")
    or "property-images-estatex-1"
)

AWS_ACCESS_KEY = (
    os.environ.get("AWS_ACCESS_KEY_ID") 
    or os.environ.get("AWS_ACCESS_KEY")
)

AWS_SECRET_KEY = (
    os.environ.get("AWS_SECRET_ACCESS_KEY") 
    or os.environ.get("AWS_SECRET_KEY")
)

AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

# Google GenAI Configuration
ai_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# --- HELPER FUNCTION: Enforce Exact JSON Structure ---
# --- HELPER FUNCTION: Enforce Exact JSON Structure (Crash-Proof) ---
def enforce_exact_json_structure(data, s3_urls):
    # अगर data खुद एक String है, तो उसे पहले JSON dict में parse करने की कोशिश करें
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    elif not isinstance(data, dict):
        data = {}

    def safe_get_dict(obj, key):
        val = obj.get(key, {}) if isinstance(obj, dict) else {}
        return val if isinstance(val, dict) else {}

    cat = safe_get_dict(data, "category")
    cnt = safe_get_dict(data, "contact")
    td = safe_get_dict(data, "title_and_description")
    loc = safe_get_dict(data, "location")
    prc = safe_get_dict(data, "pricing")
    spec = safe_get_dict(data, "specifications")
    med = safe_get_dict(data, "media")

    return {
        "user_id": data.get("user_id", "ADMIN") if isinstance(data, dict) else "ADMIN",
        "posted_by_type": data.get("posted_by_type", "ADMIN") if isinstance(data, dict) else "ADMIN",
        "category": {
            "purpose": cat.get("purpose", "BUY"),
            "property_type": cat.get("property_type", "RESIDENTIAL"),
            "sub_type": cat.get("sub_type", "FLAT_APARTMENT")
        },
        "contact": {
            "owner_name": cnt.get("owner_name", "ADMIN"),
            "phone": cnt.get("phone", "na"),
            "owner_type": cnt.get("owner_type", "AGENT")
        },
        "title_and_description": {
            "title": td.get("title", "na"),
            "description": td.get("description", "na")
        },
        "location": {
            "city": loc.get("city", "Kolkata"),
            "locality": loc.get("locality", "na"),
            "sub_locality": loc.get("sub_locality", "na"),
            "landmark": loc.get("landmark", "na"),
            "pincode": loc.get("pincode", "na"),
            "state": loc.get("state", "West Bengal"),
            "full_address": loc.get("full_address", "na")
        },
        "pricing": {
            "price_display": prc.get("price_display", "na"),
            "price_numeric": prc.get("price_numeric", "na"),
            "is_negotiable": prc.get("is_negotiable", True)
        },
        "specifications": {
            "bhk_type": spec.get("bhk_type", "na"),
            "bhk_numeric": spec.get("bhk_numeric", "na"),
            "builtup_sqft": spec.get("builtup_sqft", "na"),
            "carpet_sqft": spec.get("carpet_sqft", "na"),
            "super_builtup_sqft": spec.get("super_builtup_sqft", "na"),
            "floor_no": spec.get("floor_no", "na"),
            "total_floors": spec.get("total_floors", "na"),
            "bathrooms": spec.get("bathrooms", "na"),
            "balconies": spec.get("balconies", "na"),
            "furnishing_status": spec.get("furnishing_status", "na"),
            "construction_status": spec.get("construction_status", "na"),
            "facing_direction": spec.get("facing_direction", "NORTH WEST"),
            "property_age": spec.get("property_age", "na"),
            "parking": spec.get("parking", "YES"),
            "ownership_type": spec.get("ownership_type", "FREEHOLD")
        },
        "amenities": data.get("amenities", []) if isinstance(data, dict) and isinstance(data.get("amenities"), list) else [],
        "media": {
            "images": med.get("images", s3_urls) if isinstance(med.get("images"), list) else s3_urls,
            "ai_short_video_url": med.get("ai_short_video_url", "na")
        },
        "created_at": data.get("created_at", "few years") if isinstance(data, dict) else "few years"
    }
    
# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html', db_name=DB_NAME, collection_name=COLLECTION_NAME)

@app.route('/api/upload-s3', methods=['POST'])
def upload_s3():
    if 'images' not in request.files:
        return jsonify({"success": False, "error": "No images provided"}), 400
    
    files = request.files.getlist('images')
    uploaded_urls = []

    try:
        for file in files:
            filename = file.filename
            
            s3_client.upload_fileobj(
                file,
                S3_BUCKET,
                filename,
                ExtraArgs={'ContentType': file.content_type}
            )
            file_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{filename}"
            uploaded_urls.append(file_url)
        
        return jsonify({"success": True, "urls": uploaded_urls}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/extract-json', methods=['POST'])
def extract_json():
    if 'data_images' not in request.files:
        return jsonify({"success": False, "error": "No property detail images provided"}), 400
    
    data_files = request.files.getlist('data_images')
    s3_urls_raw = request.form.get('s3_urls', '[]')
    s3_urls = json.loads(s3_urls_raw)

    try:
        contents = [
            "Extract property details from these images and return strictly a valid JSON object matching "
            "the standard property schema (user_id, category, contact, title_and_description, location, "
            "pricing, specifications, amenities, media, created_at). Do not add any extra text, markdown ticks only if necessary."
        ]

        for file in data_files:
            img = Image.open(file.stream)
            img = img.convert("RGB")
            img.thumbnail((1024, 1024))
            
            byte_arr = io.BytesIO()
            img.save(byte_arr, format='JPEG', quality=80)
            image_bytes = byte_arr.getvalue()

            contents.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type='image/jpeg'
                )
            )
       
        # 🔄 Active Gemini Model for google-genai SDK
                # 🔄 Free-Tier Optimized Gemini Flash Models
        models_to_try = [
            'gemini-3.6-flash',
            'gemini-3.1-flash-preview',
            'gemini-2.5-flash'
        ]
        
        
        response = None
        last_error = None

        for model_name in models_to_try:
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=contents
                )
                if response and response.text:
                    break
            except Exception as err:
                last_error = err
                continue

        if not response or not response.text:
            raise Exception(f"All Gemini models failed. Last error: {str(last_error)}")
        
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        parsed_json = json.loads(cleaned_text)

        final_ordered_json = enforce_exact_json_structure(parsed_json, s3_urls)

        return jsonify({"success": True, "data": final_ordered_json}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/submit-to-db', methods=['POST'])
def submit_to_db():
    try:
        req_data = request.get_json()
        raw_text = req_data.get('json_data', '')
        
        parsed_data = json.loads(raw_text)
        result = collection.insert_one(parsed_data)
        
        return jsonify({
            "success": True, 
            "message": f"Data successfully submitted to Database! ID: {str(result.inserted_id)}"
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
    
