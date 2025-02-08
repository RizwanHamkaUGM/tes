from flask import Flask, request, jsonify, send_file
from graphviz import Digraph
import os
from firebase_admin import credentials, initialize_app, db
from flask_cors import CORS
import tempfile
from datetime import datetime

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Gunakan temporary directory untuk file static
STATIC_FOLDER = tempfile.gettempdir()

# Inisialisasi Firebase dengan credential dari environment variable
cred_dict = {
    "type": "service_account",
    "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
    "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_CERT_URL")
}

cred = credentials.Certificate(cred_dict)
initialize_app(cred, {
    "databaseURL": os.environ.get("FIREBASE_DATABASE_URL")
})


def load_data():
    """Memuat data keluarga dari Firebase."""
    ref = db.reference("family")
    family_data = ref.get()
    return {"family": family_data} if family_data else {"family": []}

def save_data(data):
    """Menyimpan data keluarga ke Firebase."""
    ref = db.reference("family")
    ref.set(data["family"])

def calculate_relationship(family, member_id):
    """Menghitung hubungan antara anggota keluarga."""
    relationships = {}
    id_to_member = {member["id"]: member for member in family}

    for member in family:
        if member["id"] == member_id:
            continue

        parent1_id = member.get("parent1_id")
        parent2_id = member.get("parent2_id")
        member_parents = (parent1_id, parent2_id)

        # Hubungan logis
        if member_id in member_parents:
            relationships[member["id"]] = "Anak"
        elif any(
            id_to_member.get(parent_id, {}).get("parent1_id") == member_id
            for parent_id in member_parents if parent_id
        ):
            relationships[member["id"]] = "Cucu"
        elif member_id in (
            id_to_member.get(parent1_id, {}).get("parent1_id"),
            id_to_member.get(parent1_id, {}).get("parent2_id"),
        ):
            relationships[member["id"]] = "Keponakan"
        elif parent1_id and id_to_member.get(parent1_id, {}).get("parent1_id") == id_to_member.get(member_id, {}).get("parent1_id"):
            relationships[member["id"]] = "Saudara"

    return relationships

def generate_family_tree(family):
    """Menghasilkan silsilah keluarga dalam format PNG menggunakan Graphviz dengan temporary directory."""
    # Buat temporary directory
    temp_dir = tempfile.mkdtemp()
    
    # Buat instance Digraph dengan directory temporary
    graph = Digraph(format="png")
    graph.attr(rankdir="TB")

    # Tambahkan node untuk setiap anggota keluarga
    for member in family:
        graph.node(
            str(member["id"]),
            label=f'{member["name"]}\n({member.get("anggota", "")})',
            shape="box",
        )

    # Tambahkan edge untuk hubungan orang tua-anak
    for member in family:
        if "parent1_id" in member and member["parent1_id"]:
            graph.edge(str(member["parent1_id"]), str(member["id"]))
        if "parent2_id" in member and member["parent2_id"]:
            graph.edge(str(member["parent2_id"]), str(member["id"]))

    # Buat nama file unik dengan timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(temp_dir, f"family_tree_{timestamp}")
    
    try:
        # Render graph ke file temporary
        graph.render(output_path, format="png", cleanup=True)
        
        # Path lengkap ke file PNG yang dihasilkan
        full_path = f"{output_path}.png"
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")
        
        return full_path
        
    except Exception as e:
        print(f"Error generating family tree: {str(e)}")
        raise

@app.route("/family", methods=["GET"])
def get_family():
    """Mengembalikan data keluarga."""
    data = load_data()
    return jsonify(data)

@app.route("/family", methods=["POST"])
def add_family_member():
    """Menambahkan anggota keluarga baru."""
    data = load_data()
    new_member = request.json

    # Validasi properti wajib
    required_fields = ["id", "name", "anggota"]
    for field in required_fields:
        if field not in new_member:
            return jsonify({"error": f"Field '{field}' is required"}), 400

    # Tambahkan properti opsional jika tidak ada
    new_member.setdefault("parent1_id", None)
    new_member.setdefault("parent2_id", None)

    data["family"].append(new_member)
    save_data(data)
    return jsonify({"message": "Member added successfully"}), 201

@app.route("/family/relationship/<int:member_id>", methods=["GET"])
def describe_relationship(member_id):
    """Menghitung dan mengembalikan hubungan keluarga untuk anggota tertentu."""
    data = load_data()["family"]
    relationships = calculate_relationship(data, member_id)
    
    if not relationships:
        return jsonify([]), 200  # Jika tidak ada hubungan ditemukan, kembalikan array kosong

    response = [
        {
            "id": related_id,
            "name": next(
                (member["name"] for member in data if member["id"] == related_id),
                "Unknown"
            ),
            "relationship": relationship,
        }
        for related_id, relationship in relationships.items()
    ]
    return jsonify(response)

@app.route("/family/tree", methods=["GET"])
def family_tree():
    """Endpoint untuk menghasilkan dan mengirim file PNG silsilah keluarga."""
    try:
        data = load_data()["family"]
        image_path = generate_family_tree(data)
        
        # Kirim file dan set callback untuk menghapus file setelah terkirim
        return send_file(
            image_path,
            mimetype="image/png",
            as_attachment=True,
            download_name="family_tree.png"
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
    finally:
        # Cleanup: hapus file temporary jika masih ada
        try:
            if 'image_path' in locals() and os.path.exists(image_path):
                os.remove(image_path)
                os.rmdir(os.path.dirname(image_path))
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

@app.route("/family/<int:member_id>", methods=["PUT"])
def update_family_member(member_id):
    """Memperbarui data anggota keluarga berdasarkan ID."""
    data = load_data()
    updated_data = request.json

    for member in data["family"]:
        if member["id"] == member_id:
            member["name"] = updated_data.get("name", member["name"])
            member["anggota"] = updated_data.get("anggota", member["anggota"])
            member["parent1_id"] = updated_data.get("parent1_id", member["parent1_id"])
            member["parent2_id"] = updated_data.get("parent2_id", member["parent2_id"])
            save_data(data)
            return jsonify({"message": "Member updated successfully"}), 200

    return jsonify({"error": "Member not found"}), 404

@app.route("/family/<int:member_id>", methods=["DELETE"])
def delete_family_member(member_id):
    """Menghapus anggota keluarga berdasarkan ID."""
    data = load_data()
    updated_family = [member for member in data["family"] if member["id"] != member_id]

    if len(updated_family) == len(data["family"]):
        return jsonify({"error": "Member not found"}), 404

    save_data({"family": updated_family})
    return jsonify({"message": "Member deleted successfully"}), 200

@app.route("/family", methods=["OPTIONS"])
@app.route("/family/<int:member_id>", methods=["OPTIONS"])
def handle_options():
    return "", 200  

if __name__ == "__main__":
    app.run(debug=True)