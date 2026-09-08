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
def enforce_exact_json_structure(data, s3_urls):
    return {
        "user_id": data.get("user_id", "ADMIN"),
        "posted_by_type": data.get("posted_by_type", "ADMIN"),
        "category": {
            "purpose": data.get("category", {}).get("purpose", "BUY"),
            "property_type": data.get("category", {}).get("property_type", "RESIDENTIAL"),
            "sub_type": data.get("category", {}).get("sub_type", "FLAT_APARTMENT")
        },
        "contact": {
            "owner_name": data.get("contact", {}).get("owner_name", "ADMIN"),
            "phone": data.get("contact", {}).get("phone", "na"),
            "owner_type": data.get("contact", {}).get("owner_type", "AGENT")
        },
        "title_and_description": {
            "title": data.get("title_and_description", {}).get("title", "na"),
            "description": data.get("title_and_description", {}).get("description", "na")
        },
        "location": {
            "city": data.get("location", {}).get("city", "Kolkata"),
            "locality": data.get("location", {}).get("locality", "na"),
            "sub_locality": data.get("location", {}).get("sub_locality", "na"),
            "landmark": data.get("location", {}).get("landmark", "na"),
            "pincode": data.get("location", {}).get("pincode", "na"),
            "state": data.get("location", {}).get("state", "West Bengal"),
            "full_address": data.get("location", {}).get("full_address", "na")
        },
        "pricing": {
            "price_display": data.get("pricing", {}).get("price_display", "na"),
            "price_numeric": data.get("pricing", {}).get("price_numeric", "na"),
            "is_negotiable": data.get("pricing", {}).get("is_negotiable", True)
        },
        "specifications": {
            "bhk_type": data.get("specifications", {}).get("bhk_type", "na"),
            "bhk_numeric": data.get("specifications", {}).get("bhk_numeric", "na"),
            "builtup_sqft": data.get("specifications", {}).get("builtup_sqft", "na"),
            "carpet_sqft": data.get("specifications", {}).get("carpet_sqft", "na"),
            "super_builtup_sqft": data.get("specifications", {}).get("super_builtup_sqft", "na"),
            "floor_no": data.get("specifications", {}).get("floor_no", "na"),
            "total_floors": data.get("specifications", {}).get("total_floors", "na"),
            "bathrooms": data.get("specifications", {}).get("bathrooms", "na"),
            "balconies": data.get("specifications", {}).get("balconies", "na"),
            "furnishing_status": data.get("specifications", {}).get("furnishing_status", "na"),
            "construction_status": data.get("specifications", {}).get("construction_status", "na"),
            "facing_direction": data.get("specifications", {}).get("facing_direction", "NORTH WEST"),
            "property_age": data.get("specifications", {}).get("property_age", "na"),
            "parking": data.get("specifications", {}).get("parking", "YES"),
            "ownership_type": data.get("specifications", {}).get("ownership_type", "FREEHOLD")
        },
        "amenities": data.get("amenities", []),
        "media": {
            "images": data.get("media", {}).get("images", s3_urls),
            "ai_short_video_url": data.get("media", {}).get("ai_short_video_url", "na")
        },
        "created_at": data.get("created_at", "few years")
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

        # 🔄 Gemini के सभी आधिकारिक और सक्रिय मॉडल्स की फ़ॉलबैक लिस्ट
        models_to_try = [
            'gemini-2.5-flash',
            'gemini-2.5-pro'
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
    
