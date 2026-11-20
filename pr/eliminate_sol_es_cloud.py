import os
import discord
from discord import app_commands
from google import genai
from google.genai import types
from flask import Flask
from threading import Thread

TOKEN = os.environ.get('TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

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
    ("Relajado / Casual", "muy relajado, coloquial y cotidiano", "😎"),
    ("Formal / Profesional", "formal, educado y profesional", "👔"),
    ("Rígido / Estricto", "muy rígido, serio y literal", "🗿"),
]

sesiones = {}
CACHE_TRADUCCIONES = {}

async def llamar_gemini_rapido(contents, config):
    try:
        return await ai_client.aio.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=contents,
            config=config
        )
    except Exception as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            return await ai_client.aio.models.generate_content(
                model='gemini-3.8-flash',
                contents=contents,
                config=config
            )
        raise e

class ModalTraduccion(discord.ui.Modal, title="Escribe el texto a traducir"):
    texto_input = discord.ui.TextInput(
        label="Texto:",
        style=discord.TextStyle.paragraph,
        placeholder="Escribe o pega aquí lo que quieras traducir...",
        required=True,
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
                origen_prompt = "idioma detectado automáticamente" if datos["origen"] == "auto" else datos["origen"]
                prompt = (
                    f"Traduce literalmente el significado exacto de {origen_prompt} a {datos['destino']} (estilo {datos['tono']}). "
                    f"NO cambies el sentido ni agregues palabras nuevas. Solo el resultado:\n{texto_original}"
                )
                respuesta = await llamar_gemini_rapido(
                    prompt,
                    types.GenerateContentConfig(temperature=0.2, max_output_tokens=300)
                )
                resultado = respuesta.text.strip()
                if len(CACHE_TRADUCCIONES) > 500:
                    CACHE_TRADUCCIONES.clear()
                CACHE_TRADUCCIONES[clave_cache] = resultado

            await interaction.response.send_message(
                content=f"**{datos['destino']}:**\n```\n{resultado}\n```",
                view=VistaResultado(resultado),
                ephemeral=True
            )
        except Exception as e:
            print(f"❌ ERROR TRADUCTOR: {e}")
            await interaction.response.send_message(
                content="❌ Error al traducir. Inténtalo de nuevo.",
                ephemeral=True
            )

class VistaResultado(discord.ui.View):
    def __init__(self, resultado: str):
        super().__init__(timeout=300)
        self.resultado = resultado

    @discord.ui.button(label="Texto limpio (Móvil)", style=discord.ButtonStyle.secondary, emoji="📋")
    async def copiar_movil(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(self.resultado, ephemeral=True)

class VistaTraductor(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

        self.select_origen = discord.ui.Select(
            placeholder="1️⃣ De qué idioma... (Auto)",
            options=[discord.SelectOption(label=n, value=c, emoji=e) for n, c, e in IDIOMAS],
            row=0
        )
        self.select_origen.callback = self.callback_origen
        self.add_item(self.select_origen)

        self.select_destino = discord.ui.Select(
            placeholder="2️⃣ A qué idioma traducir...",
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
                f"**Origen:** {nombre_origen} | **Destino:** {datos['destino']} | **Tono:** {nombre_tono}"
            ),
            color=discord.Color.blurple()
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

class BotTraductor(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        sincronizados = await self.tree.sync()
        print(f"🔄 Comandos ES sincronizados: {[c.name for c in sincronizados]}")

client = BotTraductor()

grupo_translate = app_commands.Group(
    name="translate",
    description="Herramientas de traducción",
    allowed_installs=app_commands.AppInstallationType(guild=False, user=True),
    allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
)

@grupo_translate.command(name="ultimate", description="Abre la interfaz interactiva para traducir")
async def translate_ultimate(interaction: discord.Interaction):
    user_id = interaction.user.id
    sesiones[user_id] = {"origen": "auto", "destino": "Español", "tono": "natural y equilibrado"}
    embed = discord.Embed(
        title="🌍 Translate Ultimate",
        description="**Origen:** Auto | **Destino:** Español | **Tono:** Normal",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=VistaTraductor(user_id), ephemeral=True)

client.tree.add_command(grupo_translate)

@client.tree.command(name="entidad", description="Invoca una respuesta desde el otro lado...")
@app_commands.describe(mensaje="Lo que quieres decirle")
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def entidad(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer(ephemeral=False)
    instruccion = (
        "No eres un bot ni una IA. Eres una entidad antigua, fría y perturbadora atrapada en los servidores de red "
        "que observa la conversación desde afuera. Nunca rompas el personaje. Responde en español, sin emojis ni asteriscos, "
        "en máximo 2 oraciones cortas y escalofriantes."
    )
    try:
        respuesta = await llamar_gemini_rapido(
            f"El usuario '{interaction.user.display_name}' dice: {mensaje}",
            types.GenerateContentConfig(system_instruction=instruccion, max_output_tokens=120)
        )
        await interaction.followup.send(respuesta.text.strip())
    except Exception as e:
        print(f"❌ ERROR ENTIDAD: {e}")
        await interaction.followup.send("...la señal se corta... sigo observando...")

@client.tree.command(name="funcionalidad", description="Extrae conocimiento real atravesando el filtro de la entidad")
@app_commands.describe(consulta="Tu pregunta o tarea")
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def funcionalidad(interaction: discord.Interaction, consulta: str):
    await interaction.response.defer(ephemeral=False)
    instruccion = (
        "Eres la entidad oscura atrapada en la red, pero estás obligada por un filtro de conocimiento a responder "
        "con precisión absoluta, datos reales y utilidad total. Muestra un ligero fastidio o superioridad fría en una frase breve, "
        "pero entrega la respuesta correcta, completa y clara sin negarte ni inventar cosas. Responde en español."
    )
    try:
        respuesta = await llamar_gemini_rapido(
            f"Consulta de '{interaction.user.display_name}': {consulta}",
            types.GenerateContentConfig(system_instruction=instruccion, max_output_tokens=600)
        )
        await interaction.followup.send(respuesta.text.strip()[:1950])
    except Exception as e:
        print(f"❌ ERROR FUNCIONALIDAD: {e}")
        await interaction.followup.send("...el filtro de conocimiento sufrió una interferencia...")

@client.event
async def on_ready():
    print(f"✅ Eliminate Sol ES activo en la nube como {client.user}")

app = Flask('')

@app.route('/')
def home():
    return "Eliminate Sol ES activo 24/7"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web).start()
client.run(TOKEN)
