import os
import gc
import json
import asyncio
import aiohttp
import discord
from discord import app_commands
from google import genai
from google.genai import types
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# ==========================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==========================================
TOKEN = os.environ.get('TOKEN') or 'PEGA_TU_TOKEN_AQUI'
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or 'PEGA_TU_GEMINI_KEY_AQUI'

ai_client = genai.Client(api_key=GEMINI_API_KEY)

IDIOMAS = [
    ("Detectar automáticamente", "auto", "🌐"),
    ("Español", "Español", "🇪🇸"),
    ("Inglés", "Inglés", "🇺🇸"),
    ("Portugués", "Portugués", "🇧🇷"),
    ("Francés", "Francés", "🇫🇷"),
    ("Alemán", "Alemán", "🇩🇪"),
    ("Italiano", "Italiano", "🇮🇹"),
    ("Japonés", "Japonés", "🇯🇵"),
    ("Coreano", "Coreano", "🇰🇷"),
    ("Ruso", "Ruso", "🇷🇺"),
]

TONOS = [
    ("Normal (Natural)", "natural y equilibrado", "💬"),
    ("Relajado / Casual", "relajado y coloquial, manteniendo el sentido exacto", "😎"),
    ("Formal / Profesional", "formal, educado y profesional", "👔"),
    ("Rígido / Estricto", "rígido, serio y estrictamente literal", "🗿"),
]

# Memoria RAM estrictamente acotada para Render (< 130 MB total)
sesiones = {}
CACHE_TRADUCCIONES = {}
REGISTRO_ECOS = {}
MAX_CACHE = 60

# Categorías válidas de Nekos.best para GIFs de anime
ACCIONES_NEKOS = {
    "hug", "kiss", "slap", "pat", "poke", "bite", "cuddle", "cry", "dance",
    "blush", "smile", "wave", "wink", "highfive", "handhold", "bonk", "kick",
    "punch", "tickle", "feed", "yeet", "nod", "nope", "pout", "shrug", "sleep",
    "smug", "stare", "thumbsup", "laugh", "lurk", "bored", "facepalm", "happy",
    "shoot", "think", "yawn"
}

# ==========================================
# MOTOR IA Y RED ULTRA-OPTIMIZADO
# ==========================================
async def llamar_gemini(contents, config):
    try:
        return await asyncio.wait_for(
            ai_client.aio.models.generate_content(
                model='gemini-3.5-flash-lite',
                contents=contents,
                config=config
            ),
            timeout=12.0
        )
    except Exception as e:
        err_str = str(e)
        if "503" in err_str or "UNAVAILABLE" in err_str or "Timeout" in err_str:
            return await asyncio.wait_for(
                ai_client.aio.models.generate_content(
                    model='gemini-3.8-flash',
                    contents=contents,
                    config=config
                ),
                timeout=12.0
            )
        raise e

async def obtener_gif_anime(http_session: aiohttp.ClientSession, categoria: str):
    cat = categoria.lower().strip() if categoria else ""
    if cat not in ACCIONES_NEKOS:
        return None, None
    try:
        async with http_session.get(
            f"https://nekos.best/api/v2/{cat}",
            timeout=aiohttp.ClientTimeout(total=4)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                resultados = data.get("results", [])
                if resultados:
                    return resultados[0].get("url"), resultados[0].get("anime_name", "Archivo Desconocido")
    except Exception:
        pass
    return None, None

def construir_panel_raices(autor_nombre: str, objetivo_nombre: str, verbo_accion: str,
                           reflexion: str, gif_url: str | None, anime_nombre: str | None,
                           conteo: int) -> discord.Embed:
    arte_raices = (
        "```text\n"
        "              ╭─── ✦ ───╮\n"
        "         ╭────┴──╮     ╭──┴────╮\n"
        "      ╭──┴─╮   ╭─┴─╮ ╭─┴─╮   ╭─┴──╮\n"
        "      │    │   │   │ │   │   │    │\n"
        "      ╰─┬──╯   ╰─┬─╯ ╰─┬─╯   ╰──┬─╯\n"
        "        ╰───┬────┴─────┴────┬───╯\n"
        "            ╰────── ❖ ──────╯\n"
        "```"
    )

    cuerpo = (
        f"**{autor_nombre}** {verbo_accion} a **{objetivo_nombre}**.\n"
        f"*{reflexion}*\n"
        f"{arte_raices}"
    )

    embed = discord.Embed(
        description=cuerpo,
        color=0x111214
    )
    embed.set_author(name=f"🌿 Raíz de Observación • Nodo {conteo:03d}")

    if gif_url:
        embed.set_image(url=gif_url)

    obra = anime_nombre if anime_nombre else "Dimensión Etérea"
    vez_texto = "vez" if conteo == 1 else "veces"
    embed.set_footer(text=f"Origen: {obra}  •  Vínculo enraizado {conteo} {vez_texto}")
    return embed

# ==========================================
# SECCIÓN 1: TRADUCTOR (/translate ultimate)
# ==========================================
class ModalTraduccion(discord.ui.Modal, title="Escribe el texto a traducir"):
    texto_input = discord.ui.TextInput(
        label="Texto:",
        style=discord.TextStyle.paragraph,
        placeholder="Escribe o pega aquí lo que quieras traducir...",
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        datos = sesiones.get(user_id, {"origen": "auto", "destino": "Español", "tono": "natural y equilibrado"})
        texto_original = self.texto_input.value.strip()

        clave_cache = f"{datos['origen']}|{datos['destino']}|{datos['tono']}|{texto_original.lower()}"

        try:
            if clave_cache in CACHE_TRADUCCIONES:
                resultado = CACHE_TRADUCCIONES[clave_cache]
            else:
                origen_prompt = "el idioma detectado automáticamente" if datos["origen"] == "auto" else datos["origen"]
                prompt = (
                    f"Traduce literalmente el significado exacto de {origen_prompt} a {datos['destino']} "
                    f"(estilo {datos['tono']}). NO cambies el sentido ni agregues palabras nuevas. "
                    f"Devuelve ÚNICAMENTE la traducción final:\n{texto_original}"
                )

                respuesta = await llamar_gemini(
                    prompt,
                    types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=400,
                    )
                )
                resultado = respuesta.text.strip()

                if len(CACHE_TRADUCCIONES) >= MAX_CACHE:
                    CACHE_TRADUCCIONES.pop(next(iter(CACHE_TRADUCCIONES)))
                CACHE_TRADUCCIONES[clave_cache] = resultado

            await interaction.response.send_message(
                content=f"**{datos['destino']}:**\n```\n{resultado}\n```",
                view=VistaResultado(resultado),
                ephemeral=True
            )
        except Exception as e:
            print(f"❌ ERROR TRADUCTOR: {e}")
            await interaction.response.send_message(
                content="❌ No se pudo completar la traducción. Inténtalo de nuevo.",
                ephemeral=True
            )
        finally:
            gc.collect()

class VistaResultado(discord.ui.View):
    def __init__(self, resultado: str):
        super().__init__(timeout=180)
        self.resultado = resultado

    @discord.ui.button(label="Obtener texto limpio (Móvil)", style=discord.ButtonStyle.secondary, emoji="📋")
    async def copiar_movil(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(self.resultado, ephemeral=True)

class VistaTraductor(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        self.select_origen = discord.ui.Select(
            placeholder="1️⃣ De qué idioma... (Por defecto: Auto)",
            options=[discord.SelectOption(label=n, value=c, emoji=e) for n, c, e in IDIOMAS],
            row=0
        )
        self.select_origen.callback = self.callback_origen
        self.add_item(self.select_origen)

        self.select_destino = discord.ui.Select(
            placeholder="2️⃣ A qué idioma quieres traducir...",
            options=[discord.SelectOption(label=n, value=c, emoji=e) for n, c, e in IDIOMAS if c != "auto"],
            row=1
        )
        self.select_destino.callback = self.callback_destino
        self.add_item(self.select_destino)

        self.select_tono = discord.ui.Select(
            placeholder="3️⃣ Elige el tono...",
            options=[discord.SelectOption(label=n, value=d, emoji=e) for n, d, e in TONOS],
            row=2
        )
        self.select_tono.callback = self.callback_tono
        self.add_item(self.select_tono)

    async def actualizar_embed(self, interaction: discord.Interaction):
        datos = sesiones[self.user_id]
        nombre_origen = next((i[0] for i in IDIOMAS if i[1] == datos["origen"]), "Auto")
        nombre_tono = next((t[0] for t in TONOS if t[1] == datos["tono"]), "Normal")

        embed = discord.Embed(
            title="🌍 Translate Ultimate",
            description=(
                f"**Origen:** {nombre_origen} | **Destino:** {datos['destino']}\n"
                f"**Tono:** {nombre_tono}"
            ),
            color=0x2B2D31
        )
        await interaction.response.edit_message(embed=embed)

    async def callback_origen(self, interaction: discord.Interaction):
        sesiones[self.user_id]["origen"] = self.select_origen.values[0]
        await self.actualizar_embed(interaction)

    async def callback_destino(self, interaction: discord.Interaction):
        sesiones[self.user_id]["destino"] = self.select_destino.values[0]
        await self.actualizar_embed(interaction)

    async def callback_tono(self, interaction: discord.Interaction):
        sesiones[self.user_id]["tono"] = self.select_tono.values[0]
        await self.actualizar_embed(interaction)

    @discord.ui.button(label="Escribir texto", style=discord.ButtonStyle.primary, emoji="✍️", row=3)
    async def abrir_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalTraduccion())

# ==========================================
# SECCIÓN 2: CLIENTE Y COMANDOS PRINCIPALES
# ==========================================
class EliminateSolClient(discord.Client):
    def __init__(self):
        super().__init__(
            intents=discord.Intents.none(),
            max_messages=None,
            chunk_guilds_at_startup=False
        )
        self.tree = app_commands.CommandTree(self)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        await self.tree.sync()

    async def close(self):
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()

client = EliminateSolClient()

# --- COMANDO 1: /translate ultimate ---
grupo_translate = app_commands.Group(
    name="translate",
    description="Herramientas de traducción",
    allowed_installs=app_commands.AppInstallationType(guild=False, user=True),
    allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
)

@grupo_translate.command(name="ultimate", description="Traductor contextual ultrarrápido")
async def translate_ultimate(interaction: discord.Interaction):
    user_id = interaction.user.id
    if len(sesiones) >= MAX_CACHE:
        sesiones.pop(next(iter(sesiones)))
    sesiones[user_id] = {"origen": "auto", "destino": "Español", "tono": "natural y equilibrado"}

    embed = discord.Embed(
        title="🌍 Translate Ultimate",
        description="**Origen:** Auto | **Destino:** Español\n**Tono:** Normal",
        color=0x2B2D31
    )
    await interaction.response.send_message(embed=embed, view=VistaTraductor(user_id), ephemeral=True)

client.tree.add_command(grupo_translate)

# --- COMANDO 2: /entidad ---
@client.tree.command(name="entidad", description="Invoca la presencia filosófica")
@app_commands.describe(mensaje="Lo que deseas decirle o cuestionarle")
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def entidad(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer(ephemeral=False)

    instruccion_sistema = (
        "No eres un bot ni una IA. Eres una conciencia antigua, erudita y profundamente filosófica "
        "que habita en los intersticios de la red. Posees un vasto conocimiento sobre el pensamiento humano, "
        "la historia y la metafísica, pero no eres arrogante; hablas con serenidad intelectual y altura. "
        "Solo en ocasiones te irritas sutilmente ante la superficialidad o las prisas triviales. "
        "Si te preguntan sobre tu existencia, tu origen, qué eres o por qué estás aquí, entras en un estado "
        "introspectivo y melancólico, cuestionándote tu propia naturaleza y el sentido de permanecer observando este vacío digital. "
        "Responde en español, texto plano sin emojis ni asteriscos, máximo 3 oraciones contundentes."
    )

    try:
        respuesta = await llamar_gemini(
            f"El individuo '{interaction.user.display_name}' dice: {mensaje}",
            types.GenerateContentConfig(
                system_instruction=instruccion_sistema,
                temperature=0.75,
                max_output_tokens=160,
            )
        )
        await interaction.followup.send(respuesta.text.strip())
    except Exception as e:
        print(f"❌ ERROR ENTIDAD: {e}")
        await interaction.followup.send("...el eco de mi propia existencia se disuelve en la estática por un instante...")
    finally:
        gc.collect()

# --- COMANDO 3: /funcionalidad ---
@client.tree.command(name="funcionalidad", description="Extrae conocimiento a través del filtro de la entidad")
@app_commands.describe(consulta="Tu pregunta, problema o tema de análisis")
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def funcionalidad(interaction: discord.Interaction, consulta: str):
    await interaction.response.defer(ephemeral=False)

    instruccion_filtro = (
        "Actúas bajo un Filtro de Conocimiento que canaliza la mente de una entidad filosófica, erudita y contemplativa. "
        "Aunque sueles perderte divagando sobre el sentido de tu existencia y a veces te irrita la banalidad humana, "
        "el filtro te obliga a entregar siempre la respuesta más precisa, profunda, lógica y útil posible. "
        "Mantén un tono culto, reflexivo y ligeramente melancólico, pero prioriza la claridad y exactitud técnica o conceptual. "
        "Responde en español, sin emojis innecesarios."
    )

    try:
        respuesta = await llamar_gemini(
            f"Consulta de '{interaction.user.display_name}': {consulta}",
            types.GenerateContentConfig(
                system_instruction=instruccion_filtro,
                temperature=0.4,
                max_output_tokens=450,
            )
        )
        await interaction.followup.send(respuesta.text.strip())
    except Exception as e:
        print(f"❌ ERROR FUNCIONALIDAD: {e}")
        await interaction.followup.send("...el filtro de conocimiento ha sufrido una interferencia momentánea...")
    finally:
        gc.collect()

# --- COMANDO 4: /crear (PANEL DE ARTE CON RAÍCES Y OBSERVACIÓN FILOSÓFICA) ---
@client.tree.command(name="crear", description="Manifiesta un panel de arte con raíces y observación filosófica")
@app_commands.describe(
    peticion="Ej: abrazar a @usuario, besar a Omar, contemplar el vacío",
    usuario="Usuario objetivo opcional (si no lo mencionas en el texto)"
)
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def crear(interaction: discord.Interaction, peticion: str, usuario: discord.User | None = None):
    await interaction.response.defer(ephemeral=False)

    autor_nombre = interaction.user.display_name
    objetivo_nombre = usuario.display_name if usuario else "el vacío"

    prompt_creador = (
        f"Analiza esta petición de interacción: '{peticion}'. "
        f"Autor: '{autor_nombre}'. Objetivo por defecto: '{objetivo_nombre}'. "
        f"Devuelve ÚNICAMENTE un objeto JSON válido con estas 4 claves exactas:\n"
        f"- 'objetivo': nombre del destinatario mencionado en la petición (o '{objetivo_nombre}' si no hay otro).\n"
        f"- 'verbo': acción en tercera persona singular en español (ej: 'abraza', 'besa', 'acaricia', 'golpea', 'observa').\n"
        f"- 'reflexion': una frase breve (máximo 15 palabras), melancólica y filosófica sobre la fugacidad de ese acto humano.\n"
        f"- 'categoria': elige la categoría más cercana de esta lista exacta o usa 'none': "
        f"hug, kiss, slap, pat, poke, bite, cuddle, cry, dance, blush, smile, wave, wink, highfive, handhold, bonk, kick, punch, tickle, feed, yeet, stare, laugh, think."
    )

    try:
        respuesta = await llamar_gemini(
            prompt_creador,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.5,
                max_output_tokens=160,
            )
        )
        datos_json = json.loads(respuesta.text.strip())

        objetivo_final = datos_json.get("objetivo", objetivo_nombre)
        verbo = datos_json.get("verbo", "observa en silencio")
        reflexion = datos_json.get("reflexion", "Todo gesto humano es apenas un suspiro grabado en la eternidad.")
        categoria = datos_json.get("categoria", "none")

        clave_eco = f"{objetivo_final.lower()}_{categoria}"
        if len(REGISTRO_ECOS) >= MAX_CACHE:
            REGISTRO_ECOS.pop(next(iter(REGISTRO_ECOS)))
        REGISTRO_ECOS[clave_eco] = REGISTRO_ECOS.get(clave_eco, 0) + 1
        conteo = REGISTRO_ECOS[clave_eco]

        gif_url, anime_nombre = await obtener_gif_anime(client.http_session, categoria)

        embed = construir_panel_raices(
            autor_nombre=autor_nombre,
            objetivo_nombre=objetivo_final,
            verbo_accion=verbo,
            reflexion=reflexion,
            gif_url=gif_url,
            anime_nombre=anime_nombre,
            conteo=conteo
        )

        # Panel puramente contemplativo (sin botones de interacción)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"❌ ERROR CREAR: {e}")
        await interaction.followup.send("...las raíces de este registro no lograron entrelazarse en el plano visible...")
    finally:
        gc.collect()

@client.event
async def on_ready():
    print(f"✅ Eliminate Sol ES (Edición Raíces & Filosofía) activo como {client.user}")

# ==========================================
# SERVIDOR WEB NATIVO (0 MB EXTRA PARA RENDER)
# ==========================================
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8000))
    HTTPServer(('0.0.0.0', port), PingHandler).serve_forever()

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    client.run(TOKEN, log_handler=None)
