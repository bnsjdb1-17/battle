import asyncio
import os
import re
import random
import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ---------------- CONFIGURATION ---------------- #
API_ID = int(os.environ.get("API_ID", "29224540"))
API_HASH = os.environ.get("API_HASH", "ed762081b78af1ee07cea88534303516")
STRING_SESSION = os.environ.get("STRING_SESSION")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 

HEXAMON_USERNAME = "hexamonbot" 
# ----------------------------------------------- #

if not STRING_SESSION:
    raise ValueError("✕ Error: STRING_SESSION environment variable is missing!")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# --- KEEP-ALIVE WEB SERVER ---
async def handle(request):
    return web.Response(text="Level 10 Hexamon Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"⎛ Keep-Alive server listening on port {port}")

# --- BOT STATE ---
bot_state = {
    "system_online": True,  
    "pvp_enabled": False,   
    "farm_mode": False,     
    "hunt_mode": False,
    "target_msg_id": None,  
    "target_chat_id": None,
    "whitelist": [],
    "six_l_list": [],
    "preferred_ball": "Regular Ball",
    "shiny_ball": "Ultra Ball",
    "six_l_ball": "Ultra Ball",
    "catching_current": False,
    "is_current_shiny": False,
    "is_current_6l": False,
    "hunt_count": 0,
    "hunt_limit": 0,
    "hunt_task": None
}

# --- STRICT RANDOMIZED HUNT TIMER ---
async def hunt_timer():
    if bot_state["hunt_limit"] > 0 and bot_state["hunt_count"] >= bot_state["hunt_limit"]:
        bot_state["hunt_mode"] = False
        bot_state["catching_current"] = False
        bot_state["is_current_shiny"] = False
        bot_state["is_current_6l"] = False
        try:
            await client.send_message("me", "✕ Target limit reached. Auto-Hunt halted.")
        except Exception:
            pass
        return

    delay = random.randint(4, 10)
    
    try:
        await asyncio.sleep(delay)
        if not bot_state["hunt_mode"]:
            return
            
        bot_state["hunt_count"] += 1
        await client.send_message(HEXAMON_USERNAME, "/hunt")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        try:
            await client.send_message("me", f"⚠ Internal Timer Error: {e}")
        except Exception:
            pass

async def trigger_next_hunt():
    # Force kill any stuck timer and start fresh
    if bot_state["hunt_task"]:
        bot_state["hunt_task"].cancel()
    bot_state["hunt_task"] = asyncio.create_task(hunt_timer())


# --- AI CAPTCHA SOLVER ---
async def solve_captcha(question_text):
    if not GROQ_API_KEY:
        try:
            await client.send_message("me", "⚠ GROQ_API_KEY missing! Cannot solve captcha.")
        except: pass
        return None
        
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "system", "content": "You are an automated captcha solver. Read the user's message, which contains a math word problem or trivia question. Reply with ONLY the final exact answer. Do not use full sentences. No explanations. No punctuation."},
            {"role": "user", "content": question_text}
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        try:
            await client.send_message("me", f"⚠ AI Captcha Error: {e}")
        except: pass
        return None


# --- CORE BATTLE & HUNT LOGIC ---
async def process_battle_message(message):
    text_lower = (message.raw_text or "").lower()

    # 0. CRITICAL FAILSAFE: BAN / AUTOMATION DETECTION
    ban_keywords = ["automation activities", "has been banned", "banned for", "automation detected"]
    if any(k in text_lower for k in ban_keywords):
        bot_state["system_online"] = False
        bot_state["hunt_mode"] = False
        bot_state["farm_mode"] = False
        bot_state["pvp_enabled"] = False
        if bot_state["hunt_task"]: bot_state["hunt_task"].cancel()
        await client.send_message(message.chat_id, "⨂ **FAILSAFE TRIGGERED:** Automation warning detected. Core offline.")
        return

    if not bot_state["system_online"]:
        return

    # 1. AI CAPTCHA BYPASS
    captcha_triggers = ["regular human check", "random ping for you", "before you continue", "answer to continue"]
    if any(k in text_lower for k in captcha_triggers):
        if bot_state["hunt_task"]: 
            bot_state["hunt_task"].cancel() 
            
        answer = await solve_captcha(message.raw_text)
        if answer:
            await asyncio.sleep(2.5) 
            await client.send_message(message.chat_id, answer)
            if bot_state["hunt_mode"]:
                await trigger_next_hunt() 
        return

    # 2. HUNT ITEM / TRAINER SKIP
    skip_keywords = ["found!", "trainer has challenged you", "expert trainer", "mega stone", "z-crystal", "found an egg", "found a tm", "tm found"]
    if bot_state["hunt_mode"] and any(k in text_lower for k in skip_keywords) and "shiny" not in text_lower:
        await trigger_next_hunt()
        return

    # 3. HUNT ENCOUNTER DETECTION
    if "a wild" in text_lower and "has appeared" in text_lower:
        match = re.search(r"a wild (.*?) \(lv", text_lower)
        if match:
            poke_name = match.group(1).strip().lower()
            
            bot_state["is_current_shiny"] = "✨" in text_lower or "shiny" in text_lower
            bot_state["is_current_6l"] = any(p in poke_name for p in bot_state["six_l_list"])
            
            if bot_state["is_current_shiny"]:
                bot_state["catching_current"] = True
            elif bot_state["is_current_6l"]:
                bot_state["catching_current"] = True
            else:
                bot_state["catching_current"] = any(p in poke_name for p in bot_state["whitelist"])
            
            if bot_state["hunt_mode"]:
                if bot_state["catching_current"]:
                    await asyncio.sleep(1.0)
                    try:
                        await message.click(text="Battle")
                    except Exception:
                        pass
                else:
                    await trigger_next_hunt() 
        return

    # 4. PVP / AUTO ACCEPT
    if bot_state["pvp_enabled"]:
        if "has challenged" in text_lower and "ready" in text_lower:
            await asyncio.sleep(0.8)
            try:
                await message.click(text="Ready ✅")
            except Exception:
                try:
                    await message.click(0, 0)
                except Exception:
                    pass

    # 5. AUTO SWITCH FAINTED POKEMON
    if (bot_state["pvp_enabled"] or bot_state["hunt_mode"]) and "choose your next pokemon" in text_lower:
        await asyncio.sleep(1.0)
        if message.buttons:
            for row in message.buttons:
                for btn in row:
                    if btn.text and btn.text.strip().isdigit() and 1 <= int(btn.text.strip()) <= 6:
                        try:
                            await message.click(text=btn.text.strip())
                            return
                        except Exception:
                            continue

    # 6. COMBAT & BALL SELECTION
    if (bot_state["pvp_enabled"] or bot_state["hunt_mode"]) and any(k in text_lower for k in ["current turn:", "battle begins", "broke free"]):
        if not message.buttons:
            return

        all_buttons = [btn.text.lower().strip() for row in message.buttons for btn in row if btn.text]
        is_main_menu = any("poke ball" in b for b in all_buttons)
        is_ball_menu = any("back" == b for b in all_buttons) or any("ball x" in b for b in all_buttons)

        # -- A. On Ball Selection Menu --
        if is_ball_menu and bot_state["catching_current"]:
            await asyncio.sleep(1.0)
            
            if bot_state["is_current_shiny"]:
                target_ball = bot_state["shiny_ball"]
            elif bot_state["is_current_6l"]:
                target_ball = bot_state["six_l_ball"]
            else:
                target_ball = bot_state["preferred_ball"]
            
            try:
                clicked = False
                for i, row in enumerate(message.buttons):
                    for j, btn in enumerate(row):
                        if target_ball.lower() in (btn.text or "").lower():
                            await message.click(i, j)
                            clicked = True
                            break
                    if clicked: break
                
                if not clicked:
                    for i, row in enumerate(message.buttons):
                        for j, btn in enumerate(row):
                            if "ball x" in (btn.text or "").lower():
                                await message.click(i, j)
                                clicked = True
                                break
                        if clicked: break
            except Exception:
                pass
            return

        # -- B. On Main Battle Menu --
        elif is_main_menu:
            await asyncio.sleep(1.0)
            if bot_state["hunt_mode"] and bot_state["catching_current"]:
                try:
                    for i, row in enumerate(message.buttons):
                        for j, btn in enumerate(row):
                            if "poke ball" in (btn.text or "").strip().lower():
                                await message.click(i, j)
                                return
                except Exception:
                    pass
            else:
                try:
                    for i, row in enumerate(message.buttons):
                        for j, btn in enumerate(row):
                            btn_text = (btn.text or "").lower().strip()
                            if btn_text and not any(k in btn_text for k in ["poke ball", "run", "pokemon", "back"]):
                                await message.click(i, j)
                                return
                except Exception:
                    pass
            return

    # 7. ENCOUNTER END / RESTART LOOPS
    if bot_state["hunt_mode"] and any(k in text_lower for k in ["you caught a wild", "fled"]):
        bot_state["catching_current"] = False
        bot_state["is_current_shiny"] = False
        bot_state["is_current_6l"] = False
        await trigger_next_hunt()

    if bot_state["farm_mode"] and any(k in text_lower for k in ["has defeated", "prize:", "forfeit", "won the battle"]):
        if bot_state["target_msg_id"]:
            await asyncio.sleep(4.0) 
            try:
                await client.send_message(bot_state["target_chat_id"], "/challenge", reply_to=bot_state["target_msg_id"])
            except Exception:
                pass

    # 8. LIMITS
    if "limit reached" in text_lower or "cannot battle" in text_lower:
        bot_state["farm_mode"] = False
        bot_state["hunt_mode"] = False
        if bot_state["hunt_task"]: bot_state["hunt_task"].cancel()


# --- OUTGOING COMMANDS (WITH STRICT MODE LOCK) ---
@client.on(events.NewMessage(outgoing=True))
async def on_outgoing_message(event):
    cmd = event.raw_text.strip().lower()
    
    # --- MASTER SWITCH ---
    if cmd == ".shut down":
        bot_state["system_online"] = False
        bot_state["pvp_enabled"] = False
        bot_state["farm_mode"] = False
        bot_state["hunt_mode"] = False
        if bot_state["hunt_task"]: bot_state["hunt_task"].cancel()
        await event.edit("✕ **SYSTEM OFFLINE.** Core suspended. Send `.wake up` to restore.")
        return
        
    elif cmd == ".wake up":
        bot_state["system_online"] = True
        await event.edit("⏻ **SYSTEM ONLINE.** Awaiting input.")
        return
        
    if not bot_state["system_online"]:
        return

    is_combat_active = bot_state["pvp_enabled"] or bot_state["farm_mode"]
    is_hunt_active = bot_state["hunt_mode"]

    if cmd == ".pvp on":
        if is_hunt_active:
            await event.edit("⚠ **MODE LOCK:** Auto-Hunt active. Override with `.hunt off`.")
            return
        bot_state["pvp_enabled"] = True
        await event.edit("✓ **PVP ACTIVE**")
        
    elif cmd == ".pvp off":
        bot_state["pvp_enabled"] = False
        await event.edit("✕ **PVP INACTIVE**")
        
    elif cmd == ".start":
        if is_hunt_active:
            await event.edit("⚠ **MODE LOCK:** Auto-Hunt active. Override with `.hunt off`.")
            return
        bot_state["farm_mode"] = True
        await event.edit("✓ **FARM STANDBY.** Reply to target with `/challenge`.")
        
    elif cmd == ".stop":
        bot_state["farm_mode"] = False
        bot_state["target_msg_id"] = None
        await event.edit("✕ **FARM HALTED**")
        
    elif cmd == ".hunt on":
        if is_combat_active:
            await event.edit("⚠ **MODE LOCK:** Combat protocols active. Halt them first.")
            return
        bot_state["hunt_mode"] = True
        bot_state["hunt_count"] = 1
        limit_txt = str(bot_state["hunt_limit"]) if bot_state["hunt_limit"] > 0 else "Infinite"
        await event.edit(f"✓ **HUNT INITIATED** (Limit: {limit_txt})")
        await client.send_message(HEXAMON_USERNAME, "/hunt")
        
    elif cmd == ".hunt off":
        bot_state["hunt_mode"] = False
        bot_state["catching_current"] = False
        bot_state["is_current_shiny"] = False
        bot_state["is_current_6l"] = False
        if bot_state["hunt_task"]: bot_state["hunt_task"].cancel()
        await event.edit("✕ **HUNT HALTED**")
        
    elif any(cmd.startswith(prefix) for prefix in [".limit", "/add", "/rm", "/clear", "/ball", "/shiny", "/6l", "/add6l", "/rm6l", "/clear6l"]):
        if is_combat_active:
            await event.edit("⚠ **MODE LOCK:** Settings locked during combat.")
            return

        if cmd.startswith(".limit "):
            try:
                val = int(cmd.replace(".limit", "").strip())
                bot_state["hunt_limit"] = val
                await event.edit(f"⌖ **Target Limit:** {val}")
            except ValueError:
                await event.edit("⚠ **Invalid format.** Use: `.limit 100`")
            
        elif cmd.startswith("/add6l "):
            pokes = [p.strip().lower() for p in cmd.replace("/add6l", "").split(",") if p.strip()]
            bot_state["six_l_list"].extend(pokes)
            bot_state["six_l_list"] = list(set(bot_state["six_l_list"]))
            await event.edit(f"✓ **6L List Updated:** {', '.join(bot_state['six_l_list']).title()}")
            
        elif cmd.startswith("/rm6l "):
            pokes = [p.strip().lower() for p in cmd.replace("/rm6l", "").split(",") if p.strip()]
            for p in pokes:
                if p in bot_state["six_l_list"]:
                    bot_state["six_l_list"].remove(p)
            wl_str = ", ".join(bot_state['six_l_list']).title() if bot_state['six_l_list'] else "None"
            await event.edit(f"⌫ **6L Target Removed.**\n**6L List:** {wl_str}")
            
        elif cmd == "/clear6l":
            bot_state["six_l_list"] = []
            await event.edit("⌫ **6L List Cleared.**")

        elif cmd.startswith("/add "):
            pokes = [p.strip().lower() for p in cmd.replace("/add", "").split(",") if p.strip()]
            bot_state["whitelist"].extend(pokes)
            bot_state["whitelist"] = list(set(bot_state["whitelist"]))
            await event.edit(f"✓ **Whitelist Updated:** {', '.join(bot_state['whitelist']).title()}")
            
        elif cmd.startswith("/rm "):
            pokes = [p.strip().lower() for p in cmd.replace("/rm", "").split(",") if p.strip()]
            for p in pokes:
                if p in bot_state["whitelist"]:
                    bot_state["whitelist"].remove(p)
            wl_str = ", ".join(bot_state['whitelist']).title() if bot_state['whitelist'] else "None"
            await event.edit(f"⌫ **Target Removed.**\n**Whitelist:** {wl_str}")
            
        elif cmd == "/clear":
            bot_state["whitelist"] = []
            await event.edit("⌫ **Whitelist Cleared.**")
            
        elif cmd.startswith("/ball "):
            ball = cmd.replace("/ball", "").strip().lower()
            if "ultra" in ball: bot_state["preferred_ball"] = "Ultra Ball"
            elif "great" in ball: bot_state["preferred_ball"] = "Great Ball"
            elif "master" in ball: bot_state["preferred_ball"] = "Master Ball"
            elif "repeat" in ball: bot_state["preferred_ball"] = "Repeat Ball"
            else: bot_state["preferred_ball"] = "Regular Ball"
            await event.edit(f"◓ **Standard Ball:** {bot_state['preferred_ball']}")

        elif cmd.startswith("/shiny "):
            ball = cmd.replace("/shiny", "").strip().lower()
            if "ultra" in ball: bot_state["shiny_ball"] = "Ultra Ball"
            elif "great" in ball: bot_state["shiny_ball"] = "Great Ball"
            elif "master" in ball: bot_state["shiny_ball"] = "Master Ball"
            elif "repeat" in ball: bot_state["shiny_ball"] = "Repeat Ball"
            else: bot_state["shiny_ball"] = "Regular Ball"
            await event.edit(f"✦ **Shiny Ball:** {bot_state['shiny_ball']}")
            
        elif cmd.startswith("/6l "):
            ball = cmd.replace("/6l", "").strip().lower()
            if "ultra" in ball: bot_state["six_l_ball"] = "Ultra Ball"
            elif "great" in ball: bot_state["six_l_ball"] = "Great Ball"
            elif "master" in ball: bot_state["six_l_ball"] = "Master Ball"
            elif "repeat" in ball: bot_state["six_l_ball"] = "Repeat Ball"
            else: bot_state["six_l_ball"] = "Regular Ball"
            await event.edit(f"⎈ **6L Ball:** {bot_state['six_l_ball']}")
        
    elif cmd == "/challenge" and bot_state["farm_mode"] and event.is_reply:
        reply = await event.get_reply_message()
        bot_state["target_msg_id"] = reply.id
        bot_state["target_chat_id"] = event.chat_id
            
    elif cmd == ".ping":
        sys_status = "ONLINE ⏻" if bot_state['system_online'] else "OFFLINE ✕"
        wl_str = ", ".join(bot_state['whitelist']).title() if bot_state['whitelist'] else "None"
        six_l_str = ", ".join(bot_state['six_l_list']).title() if bot_state['six_l_list'] else "None"
        lim_str = str(bot_state['hunt_limit']) if bot_state['hunt_limit'] > 0 else "∞"
        await event.edit(f"⎛ **MODULE STATUS**\n**System:** {sys_status}\n**PVP:** {bot_state['pvp_enabled']}\n**Farm:** {bot_state['farm_mode']}\n**Hunt:** {bot_state['hunt_mode']} (Count: {bot_state['hunt_count']}/{lim_str})\n**Reg Ball:** {bot_state['preferred_ball']} | **Shiny:** {bot_state['shiny_ball']} | **6L:** {bot_state['six_l_ball']}\n**Target List:** {wl_str}\n**6L List:** {six_l_str}")


if __name__ == '__main__':
    print("⟁ Level 10 Core Initialized...")
    # Register handlers for both new AND edited messages from hexamonbot
    client.on(events.NewMessage(from_users=HEXAMON_USERNAME))(on_hexamon_new_message := lambda e: process_battle_message(e.message))
    client.on(events.MessageEdited(from_users=HEXAMON_USERNAME))(on_hexamon_message_edited := lambda e: process_battle_message(e.message))
    
    client.loop.run_until_complete(start_web_server())
    client.start()
    client.run_until_disconnected()
