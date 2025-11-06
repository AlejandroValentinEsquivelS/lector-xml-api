from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import zipfile
import xml.etree.ElementTree as ET
import mysql.connector
import os
import tempfile
import hashlib

app = FastAPI(title="Procesador XML CFDI Sin Timbrado")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- VARIABLES DE ENTORNO (para Railway) ---
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "198.71.55.249"),
    "user": os.getenv("DB_USER", "pruebasroot"),
    "password": os.getenv("DB_PASSWORD", "9?EPdhwuDf12zi*v"),
    "database": os.getenv("DB_NAME", "webservice2"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "connect_timeout": 15
}

RFC_EMPRESA = os.getenv("RFC_EMPRESA", "TU_RFC_AQUI")  # ← Cambia esto

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# --- TUS FUNCIONES (SIN CAMBIOS) ---
def generar_id_unico(factura_data):
    cadena = f"{factura_data['rfc_emisor']}{factura_data['rfc_receptor']}{factura_data['serie']}{factura_data['folio']}{factura_data['fecha']}{factura_data['total']}"
    return hashlib.sha256(cadena.encode()).hexdigest()[:32]

def parse_xml(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)
        ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4', 'cfdi3': 'http://www.sat.gob.mx/cfd/3'}
        emisor = root.find('.//cfdi:Emisor', ns) or root.find('.//cfdi3:Emisor', ns)
        receptor = root.find('.//cfdi:Receptor', ns) or root.find('.//cfdi3:Receptor', ns)
        if not emisor or not receptor: return None

        rfc_emisor = emisor.get('Rfc')
        rfc_receptor = receptor.get('Rfc')
        tipo = 'emitida' if rfc_emisor == RFC_EMPRESA else 'recibida' if rfc_receptor == RFC_EMPRESA else None
        if not tipo: return None

        factura_data = {
            "rfc_emisor": rfc_emisor,
            "rfc_receptor": rfc_receptor,
            "total": float(root.get('Total', 0)),
            "fecha": root.get('Fecha', ''),
            "serie": root.get('Serie', ''),
            "folio": root.get('Folio', ''),
            "tipo": tipo,
            "moneda": root.get('Moneda', 'MXN')
        }
        factura_data['id_factura'] = generar_id_unico(factura_data)
        return factura_data
    except Exception as e:
        print(f"Error XML: {e}")
        return None

def save_to_db(factura):
    db = get_db()
    cursor = db.cursor()
    sql = """
    INSERT INTO facturas (id_factura, tipo, rfc_emisor, rfc_receptor, total, fecha, serie, folio, moneda)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE total=VALUES(total), fecha=VALUES(fecha)
    """
    cursor.execute(sql, (
        factura['id_factura'], factura['tipo'], factura['rfc_emisor'],
        factura['rfc_receptor'], factura['total'], factura['fecha'],
        factura['serie'], factura['folio'], factura['moneda']
    ))
    db.commit()
    cursor.close()
    db.close()

# --- ENDPOINTS ---
@app.post("/procesar")
async def procesar_zip(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(400, "Solo .zip")

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        content = await file.read()
        temp_zip.write(content)
        temp_zip.close()

        facturas = []
        errores = []
        with zipfile.ZipFile(temp_zip.name, 'r') as z:
            for xml_name in z.namelist():
                if xml_name.lower().endswith('.xml'):
                    try:
                        xml_data = z.read(xml_name)
                        factura = parse_xml(xml_data)
                        if factura:
                            save_to_db(factura)
                            facturas.append(factura)
                    except Exception as e:
                        errores.append(f"{xml_name}: {str(e)}")
    finally:
        os.unlink(temp_zip.name)

    return {"total": len(facturas), "procesadas": len(facturas), "errores": errores or None}

@app.get("/facturas")
def obtener_facturas():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM facturas WHERE tipo = 'emitida' ORDER BY fecha DESC")
    emitidas = cursor.fetchall()
    cursor.execute("SELECT * FROM facturas WHERE tipo = 'recibida' ORDER BY fecha DESC")
    recibidas = cursor.fetchall()
    cursor.close()
    db.close()
    return {"emitidas": emitidas, "recibidas": recibidas}

@app.get("/")
def root():
    return {
        "message": "API Procesador CFDI Sin Timbrado",
        "version": "2.0",
        "endpoints": { "POST /procesar": "Sube ZIP", "GET /facturas": "Lista facturas" }
    }

@app.get("/test-db")
def test_db():
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT 1")
        db.close()
        return {"status": "DB OK"}
    except Exception as e:
        return {"error": str(e)}