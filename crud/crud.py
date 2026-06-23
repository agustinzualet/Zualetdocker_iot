from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysqldb import MySQL
import os, logging
import paho.mqtt.publish as publish
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

logging.basicConfig(format='%(asctime)s - IoT Panel - %(levelname)s - %(message)s', level=logging.INFO)

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)

app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config["MYSQL_USER"] = os.environ["MYSQL_USER"]
app.config["MYSQL_PASSWORD"] = os.environ["MYSQL_PASSWORD"]
app.config["MYSQL_DB"] = os.environ["MYSQL_DB"]
app.config["MYSQL_HOST"] = os.environ["MYSQL_HOST"]
app.config['PERMANENT_SESSION_LIFETIME']=180
mysql = MySQL(app)

# --- MIDDLEWARE DE AUTENTICACIÓN ---

def require_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- RUTAS DE USUARIOS ---

@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    """Registrar usuario"""
    if request.method == "POST":
        if not request.form.get("usuario"):
            return "El campo usuario es obligatorio"
        elif not request.form.get("password"):
            return "El campo contraseña es obligatorio"

        passhash = generate_password_hash(request.form.get("password"), method='scrypt', salt_length=16)
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO usuarios (usuario, hash) VALUES (%s,%s)", (request.form.get("usuario"), passhash[17:]))
        if mysql.connection.affected_rows():
            flash('Se agregó un nuevo usuario al sistema')
            logging.info("Se agregó un usuario")
        mysql.connection.commit()
        return redirect(url_for('index'))

    return render_template('registrar.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not request.form.get("usuario"):
            return "El campo usuario es obligatorio"
        elif not request.form.get("password"):
            return "El campo contraseña es obligatorio"

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM usuarios WHERE usuario LIKE %s", (request.form.get("usuario"),))
        rows = cur.fetchone()
        if(rows):
            if (check_password_hash('scrypt:32768:8:1$' + rows[2], request.form.get("password"))):
                session.permanent = True
                session["user_id"] = request.form.get("usuario")
                logging.info("Se autenticó correctamente")
                return redirect(url_for('index'))
            else:
                flash('Usuario o contraseña incorrecto')
                return redirect(url_for('login'))
    return render_template('login.html')

@app.route("/logout")
@require_login
def logout():
    session.clear()
    logging.info("El usuario {} cerró su sesión".format(session.get("user_id")))
    return redirect(url_for('index'))

# --- RUTAS PRINCIPALES E IOT ---

@app.route('/')
@require_login
def index():
    # Ya no cargamos contactos, solo renderizamos el dashboard
    return render_template('index.html')

@app.route('/comando_iot', methods=['POST'])
@require_login
def comando_iot():
    """Ruta para controlar los nodos IoT vía MQTT"""
    nodo_mac = request.form.get('nodo_mac')
    accion = request.form.get('accion')

    mqtt_host = "mosquitto" 
    mqtt_user = os.environ.get("MQTT_USR")
    mqtt_pass = os.environ.get("MQTT_PASS")

    auth = {'username': mqtt_user, 'password': mqtt_pass} if mqtt_user else None

    try:
        if accion == 'destello':
            topic = f"{nodo_mac}/destello"
            publish.single(topic, payload="destello", hostname=mqtt_host, port=1883, auth=auth)
            
            flash('Orden de destello enviada a la placa')
            logging.info(f"Comando de destello MQTT enviado al nodo {nodo_mac}")

        elif accion == 'setpoint':
            nuevo_setpoint = request.form.get('setpoint_val')
            if nuevo_setpoint:
                topic = f"{nodo_mac}/setpoint"
                nuevo_setpoint_str = str(float(nuevo_setpoint.replace(",", ".")))
                publish.single(topic, payload=nuevo_setpoint_str, hostname=mqtt_host, port=1883, auth=auth)
                
                flash(f'Setpoint actualizado a {nuevo_setpoint_str}°C')
                logging.info(f"Comando de setpoint ({nuevo_setpoint_str}) MQTT enviado al nodo {nodo_mac}")

    except Exception as e:
        flash('Error al enviar el comando IoT')
        logging.error(f"Error MQTT: {e}")

    return redirect(url_for('index'))