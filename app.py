from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
import zipfile
import xml.etree.ElementTree as ET
import mysql.connector
import os
import tempfile
import hashlib
from datetime import datetime

app = FastAPI(title="Procesador XML CFDI Sin Timbrado")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    return mysql.connector.connect(
        host="198.71.55.249",
        user="pruebasroot",
        password="9?EPdhwuDf12zi*v",
        database="webservice2",
        port=3306
    )

@app.post("/procesar")
async def procesar_zip(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(400, "Solo archivos .zip son permitidos")

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

    return {
        "total": len(facturas), 
        "procesadas": len(facturas),
        "errores": errores if errores else None
    }

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

def generar_id_unico(factura_data):
    """
    Genera un ID único basado en los datos de la factura
    Similar a un UUID pero sin depender del timbre fiscal
    """
    cadena = f"{factura_data['rfc_emisor']}{factura_data['rfc_receptor']}{factura_data['serie']}{factura_data['folio']}{factura_data['fecha']}{factura_data['total']}"
    return hashlib.sha256(cadena.encode()).hexdigest()[:32]

def parse_xml(xml_bytes, rfc_empresa):
    try:
        root = ET.fromstring(xml_bytes)
        
        # Namespaces comunes del SAT
        ns = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'cfdi3': 'http://www.sat.gob.mx/cfd/3'
        }
        
        # Intentar con CFDI 4.0 primero, luego 3.3
        emisor = root.find('.//cfdi:Emisor', ns) or root.find('.//cfdi3:Emisor', ns)
        receptor = root.find('.//cfdi:Receptor', ns) or root.find('.//cfdi3:Receptor', ns)
        
        if emisor is None or receptor is None:
            return None
        
        rfc_emisor = emisor.get('Rfc')
        rfc_receptor = receptor.get('Rfc')
        
        # Validar que la factura pertenece a la empresa
        if rfc_emisor == rfc_empresa:
            tipo = 'emitida'
        elif rfc_receptor == rfc_empresa:
            tipo = 'recibida'
        else:
            return None
        
        # Extraer datos básicos
        total = float(root.get('Total', 0))
        fecha = root.get('Fecha', '')
        serie = root.get('Serie', '')
        folio = root.get('Folio', '')
        moneda = root.get('Moneda', 'MXN')
        
        # Crear diccionario de datos
        factura_data = {
            "rfc_emisor": rfc_emisor,
            "rfc_receptor": rfc_receptor,
            "total": total,
            "fecha": fecha,
            "serie": serie,
            "folio": folio,
            "tipo": tipo,
            "moneda": moneda
        }
        
        # Generar ID único basado en los datos
        factura_data['id_factura'] = generar_id_unico(factura_data)
        
        return factura_data
        
    except Exception as e:
        print(f"Error parseando XML: {str(e)}")
        return None

def save_to_db(factura):
    db = get_db()
    cursor = db.cursor()
    
    sql = """
    INSERT INTO facturas (id_factura, tipo, rfc_emisor, rfc_receptor, total, fecha, serie, folio, moneda)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE 
        total = VALUES(total),
        fecha = VALUES(fecha)
    """
    
    cursor.execute(sql, (
        factura['id_factura'],
        factura['tipo'],
        factura['rfc_emisor'],
        factura['rfc_receptor'],
        factura['total'],
        factura['fecha'],
        factura['serie'],
        factura['folio'],
        factura['moneda']
    ))
    
    db.commit()
    cursor.close()
    db.close()

@app.get("/")
def root():
    return {
        "message": "API Procesador CFDI Sin Timbrado",
        "version": "2.0",
        "endpoints": {
            "POST /procesar": "Procesa archivo ZIP con XMLs",
            "GET /facturas": "Obtiene todas las facturas"
        }
    }