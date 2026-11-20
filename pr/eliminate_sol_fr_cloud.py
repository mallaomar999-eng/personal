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

LANGUES = [
    ("Détection automatique", "auto", "🌐"),
    ("Français", "Francés", "🇫🇷"),
    ("Espagnol", "Español", "🇪🇸"),
    ("Anglais", "Inglés", "🇺🇸"),
    ("Portugais", "Portugués", "🇧🇷"),
    ("Allemand", "Alemán", "🇩🇪"),
    ("Italien", "Italiano", "🇮🇹"),
    ("Japonais", "Japonés", "🇯🇵"),
    ("Coréen", "Coreano", "🇰🇷"),
    ("Russe", "Ruso", "🇷🇺"),
]

TONS = [
    ("Normal (Naturel)", "natural y equilibrado", "💬"),
    ("Détendu / Familier", "muy relajado, coloquial y cotidiano", "😎"),
    ("Formel / Professionnel", "formal, educado y profesional", "👔"),
    ("Rigide / Strict", "muy rígido, serio y literal", "🗿"),
]

sesiones = {}
CACHE_TRADUCTIONS = {}

async def appeler_gemini_rapide(contents, config):
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

class ModalTraduction(discord.ui.Modal, title="Écrivez le texte à traduire"):
    texto_input = discord.ui.TextInput(
        label="Texte :",
        style=discord.TextStyle.paragraph,
        placeholder="Écrivez ou collez ici ce que vous voulez traduire...",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        datos = sesiones.get(user_id, {"origen": "auto", "destino": "Francés", "tono": "natural y equilibrado"})
        texto_original = self.texto_input.value.strip()
        cle_cache = f"{datos['origen']}|{datos['destino']}|{datos['tono']}|{texto_original.lower()}"

        try:
            if cle_cache in CACHE_TRADUCTIONS:
                resultado = CACHE_TRADUCTIONS[cle_cache]
            else:
                origen_prompt = "el idioma detectado automáticamente" if datos["origen"] == "auto" else datos["origen"]
                prompt = (
                    f"Traduce literalmente el significado exacto de {origen_prompt} a {datos['destino']} (estilo {datos['tono']}). "
                    f"NO cambies el sentido ni agregues palabras nuevas. Solo el resultado:\n{texto_original}"
                )
                respuesta = await appeler_gemini_rapide(
                    prompt,
                    types.GenerateContentConfig(temperature=0.2, max_output_tokens=300)
                )
                resultado = respuesta.text.strip()
                if len(CACHE_TRADUCTIONS) > 500:
                    CACHE_TRADUCTIONS.clear()
                CACHE_TRADUCTIONS[cle_cache] = resultado

            nombre_destino = next((i[0] for i in LANGUES if i[1] == datos["destino"]), "Français")
            await interaction.response.send_message(
                content=f"**{nombre_destino} :**\n```\n{resultado}\n```",
                view=VistaResultado(resultado),
                ephemeral=True
            )
        except Exception as e:
            print(f"❌ ERREUR TRADUCTEUR : {e}")
            await interaction.response.send_message(
                content="❌ Une erreur s'est produite lors de la traduction. Veuillez réessayer.",
                ephemeral=True
            )

class VistaResultado(discord.ui.View):
    def __init__(self, resultado: str):
        super().__init__(timeout=300)
        self.resultado = resultado

    @discord.ui.button(label="Texte brut (Mobile)", style=discord.ButtonStyle.secondary, emoji="📋")
    async def copiar_movil(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(self.resultado, ephemeral=True)

class VistaTraductor(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id

        self.select_origen = discord.ui.Select(
            placeholder="1️⃣ Langue source... (Auto)",
            options=[discord.SelectOption(label=n, value=c, emoji=e) for n, c, e in LANGUES],
            row=0
        )
        self.select_origen.callback = self.callback_origen
        self.add_item(self.select_origen)

        self.select_destino = discord.ui.Select(
            placeholder="2️⃣ Langue cible...",
            options=[discord.SelectOption(label=n, value=c, emoji=e) for n, c, e in LANGUES if c != "auto"],
            row=1
        )
        self.select_destino.callback = self.callback_destino
        self.add_item(self.select_destino)

        self.select_tono = discord.ui.Select(
            placeholder="3️⃣ Choisissez le ton...",
            options=[discord.SelectOption(label=n, value=d, emoji=e) for n, d, e in TONS],
            row=2
        )
        self.select_tono.callback = self.callback_tono
        self.add_item(self.select_tono)

    async def actualizar_embed(self, interaction: discord.Interaction):
        datos = sesiones[self.user_id]
        nombre_origen = next((i[0] for i in LANGUES if i[1] == datos["origen"]), "Auto")
        nombre_destino = next((i[0] for i in LANGUES if i[1] == datos["destino"]), "Français")
        nombre_tono = next((t[0] for t in TONS if t[1] == datos["tono"]), "Normal")

        embed = discord.Embed(
            title="🌍 Translate Ultimate",
            description=(
                f"**Source :** {nombre_origen} | **Cible :** {nombre_destino} | **Ton :** {nombre_tono}"
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

    @discord.ui.button(label="Écrire le texte", style=discord.ButtonStyle.primary, emoji="✍️", row=3)
    async def abrir_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalTraduction())

class BotTraductor(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        sincronizados = await self.tree.sync()
        print(f"🔄 Commandes FR synchronisées : {[c.name for c in sincronizados]}")

client = BotTraductor()

grupo_translate = app_commands.Group(
    name="translate",
    description="Outils de traduction",
    allowed_installs=app_commands.AppInstallationType(guild=False, user=True),
    allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
)

@grupo_translate.command(name="ultimate", description="Ouvre l'interface interactive pour traduire")
async def translate_ultimate(interaction: discord.Interaction):
    user_id = interaction.user.id
    sesiones[user_id] = {"origen": "auto", "destino": "Francés", "tono": "natural y equilibrado"}
    embed = discord.Embed(
        title="🌍 Translate Ultimate",
        description="**Source :** Auto | **Cible :** Français | **Ton :** Normal",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=VistaTraductor(user_id), ephemeral=True)

client.tree.add_command(grupo_translate)

@client.tree.command(name="entidad", description="Parle avec une présence douce et élégante...")
@app_commands.describe(mensaje="Ce que tu souhaites lui dire")
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def entidad(interaction: discord.Interaction, mensaje: str):
    await interaction.response.defer(ephemeral=False)
    instruccion = (
        "Tu n'es pas un bot ni une IA. Tu es une présence consciente, mature, très douce, élégante, bienveillante "
        "et protectrice qui veille sur la conversation avec le calme chaleureux d'une femme sophistiquée aimant le café fraîchement préparé. "
        "Ne mentionne jamais d'univers fictifs, de trains ni de jeux vidéo. Ne brise jamais ton personnage. "
        "Réponds toujours en français, sans astérisques de jeu de rôle, en 2 ou 3 phrases courtes, apaisantes et pleines de grâce."
    )
    try:
        respuesta = await appeler_gemini_rapide(
            f"'{interaction.user.display_name}' dit : {mensaje}",
            types.GenerateContentConfig(system_instruction=instruccion, max_output_tokens=140)
        )
        await interaction.followup.send(respuesta.text.strip())
    except Exception as e:
        print(f"❌ ERREUR ENTITÉ : {e}")
        await interaction.followup.send("...je suis toujours là près de toi, laisse-moi juste un instant pour reprendre mon souffle...")

@client.tree.command(name="funcionalidad", description="Pose une question ou demande de l'aide avec douceur et précision")
@app_commands.describe(consulta="Ta question ou ce dont tu as besoin")
@app_commands.allowed_installs(guilds=False, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def funcionalidad(interaction: discord.Interaction, consulta: str):
    await interaction.response.defer(ephemeral=False)
    instruccion = (
        "Tu es une présence mature, chaleureuse, perspicace et très aimable qui aide avec élégance et clarté. "
        "Ne mentionne aucun univers fictif ni jeu vidéo. Réponds avec précision, intelligence et douceur à la demande, "
        "comme une mentore attentionnée autour d'une tasse de café. Réponds toujours en français."
    )
    try:
        respuesta = await appeler_gemini_rapide(
            f"Demande de '{interaction.user.display_name}' : {consulta}",
            types.GenerateContentConfig(system_instruction=instruccion, max_output_tokens=600)
        )
        await interaction.followup.send(respuesta.text.strip()[:1950])
    except Exception as e:
        print(f"❌ ERREUR FONCTIONNALITÉ : {e}")
        await interaction.followup.send("...un petit nuage passe sur la ligne, réessaie dans un instant...")

@client.event
async def on_ready():
    print(f"✅ Eliminate Sol FR actif sur le cloud en tant que {client.user}")

app = Flask('')

@app.route('/')
def home():
    return "Eliminate Sol FR actif 24/7"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web).start()
client.run(TOKEN)
