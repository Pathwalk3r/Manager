from time import sleep

from discord.ext import commands
from discord import app_commands, ForumChannel, CategoryChannel, Interaction
import discord
import re
import json
import asyncio
from pathlib import Path
from ui import RemoveVerifyView, SetupVerifyView, VerifyUserView, SetupRaidView, RaidStartView
import os


MAX_MESSAGE_LENGTH = 1000

HEADER = "**Verification report:**\n\n"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = BASE_DIR + "/configs"
TEST_CONFIG_DIR =BASE_DIR + "/test_configs"
RAIDS_DIR = BASE_DIR+ "/SRC/CurrentRaids"


def get_config_dir() -> str:
    val = os.environ.get("VC_CONTROL_TESTING", "0")
    if str(val).lower() in ("1", "true", "yes"):
        return TEST_CONFIG_DIR
    return CONFIG_DIR


def ensure_configs_dir():
    os.makedirs(get_config_dir(), exist_ok=True)


def get_guild_filename(guild_id: str, guild_name: str) -> str:
    safe_name = sanitize_name(guild_name).replace(" ", "_") if guild_name else ""
    return f"{guild_id}_{safe_name}.json" if safe_name else f"{guild_id}.json"


def load_config():
    """Load all server config files from the `configs/` directory.

        Load per-server JSON files from the config directory.
        Returns a dict mapping guild_id (as string) -> config object.
    """
    # Prefer DB-backed configs when DATABASE_URL is set
    if os.environ.get("DATABASE_URL"):
        try:
            import db as _db
        except Exception:
            try:
                from . import db as _db
            except Exception:
                # fallback to filesystem if DB import fails
                _db = None

        if _db:
            try:
                return _db.load_all_configs()
            except Exception as e:
                print("DB load_all_configs failed:", e)

    ensure_configs_dir()
    configs = {}

    for fname in os.listdir(get_config_dir()):
        if not fname.lower().endswith(".json"):
            continue
        path = os.path.join(get_config_dir(), fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # skip invalid/unreadable files
            continue

        # The file should contain a single guild config object; use a filename
        # starting with the guild id to identify it.
        m = re.match(r"(\d+)", fname)
        if m:
            gid = m.group(1)
            configs[gid] = data
            continue
    return configs


def load_guild_config(guild_id: str, guild_name: str | None = None):
    """Load a single guild config. Returns the config dict or None if missing."""
    # Try DB first when available
    if os.environ.get("DATABASE_URL"):
        try:
            import db as _db
        except Exception:
            try:
                from . import db as _db
            except Exception:
                _db = None

        if _db:
            try:
                cfg = _db.load_guild_config(str(guild_id))
                if cfg is not None:
                    return cfg
            except Exception as e:
                print("DB load_guild_config failed:", e)

    ensure_configs_dir()
    gid = str(guild_id)

    # Exact filename
    fname = get_guild_filename(gid, guild_name or "")
    path = os.path.join(get_config_dir(), fname)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(e)
            return None

    # Fallback: find any file starting with the guild id
    for fname in os.listdir(get_config_dir()):
        if not fname.lower().endswith(".json"):
            continue
        if fname.startswith(gid):
            try:
                with open(os.path.join(get_config_dir(), fname), "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
    return None


def save_guild_config(guild_id: str, cfg: dict):
    """Save a single guild config to its JSON file."""
    # Prefer DB when DATABASE_URL provided
    if os.environ.get("DATABASE_URL"):
        try:
            import db as _db
        except Exception:
            try:
                from . import db as _db
            except Exception:
                _db = None

        if _db:
            try:
                _db.save_guild_config(str(guild_id), cfg)
                return
            except Exception as e:
                print("DB save_guild_config failed:", e)

    ensure_configs_dir()
    gid = str(guild_id)
    guild_name = cfg.get("name", "") if isinstance(cfg, dict) else ""
    fname = get_guild_filename(gid, guild_name)
    path = os.path.join(get_config_dir(), fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def save_raid_config(guild_id: str, cfg: dict):
    """Save a single raid config to its JSON file."""
    # Save raid state alongside the other per-guild configs so it's available
    # in the normal config directory (supports testing overrides via env).
    ensure_configs_dir()
    gid = str(guild_id)
    fname = gid + "_raid.json"
    path = os.path.join(get_config_dir(), fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def save_config(config):
    """Save the provided config mapping to per-server files in `configs/`.

    `config` should be a dict mapping guild_id (string) -> config object.
    Each guild's config is written to a separate JSON file named
    `<guild_id>_<sanitized_guild_name>.json` (or `<guild_id>.json` when name missing).
    """
    # Prefer DB when DATABASE_URL provided
    if os.environ.get("DATABASE_URL"):
        try:
            import db as _db
        except Exception:
            try:
                from . import db as _db
            except Exception:
                _db = None

        if _db:
            try:
                _db.save_config(config)
                return
            except Exception as e:
                print("DB save_config failed:", e)

    ensure_configs_dir()

    if not isinstance(config, dict):
        raise ValueError("config must be a dict mapping guild_id to config object")

    for guild_id, cfg in config.items():
        guild_name = cfg.get("name", "") if isinstance(cfg, dict) else ""
        fname = get_guild_filename(str(guild_id), guild_name)
        path = os.path.join(CONFIG_DIR, fname)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception:
            # if writing fails, skip (don't crash the whole save)
            continue

def sanitize_name(name: str) -> str:
    return re.sub(r"[^\w\s-]", "", name)[:90]

async def ensure_vc_for_thread(guild, thread, category):
    title = sanitize_name(thread.name)

    # Get or create role
    role = discord.utils.get(guild.roles, name=title)
    if role is None:
        role = await guild.create_role(name=title)

    # Check if VC already exists in the category
    if discord.utils.get(category.voice_channels, name=title):
        return False

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
    }

    await guild.create_voice_channel(
        name=title,
        category=category,
        overwrites=overwrites
    )
    return True


class VCSlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    # -----------------------------
    # /move
    # -----------------------------
    @app_commands.command(
            name="move", description="Move users between voice channels"
    )
    @app_commands.describe(
        destination_c="Channel to move users to (defaults to your current channel)",
        source_c="Channel to move users from (defaults to your current channel)",
        role="Only move users with this role",
        user="Only move this user"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def move(
        self,
        interaction: discord.Interaction,
        destination_c: discord.VoiceChannel = None,
        source_c: discord.VoiceChannel = None,
        role: discord.Role = None,
        user: discord.Member = None
    ):
        # Defer the response since moving users might take time
        await interaction.response.defer(ephemeral=True)

        # Check if the caller is in a voice channel
        caller_voice_state = interaction.user.voice
        if not caller_voice_state or not caller_voice_state.channel:
            await interaction.followup.send(
                "❌ You must be in a voice channel to use this command",
                ephemeral=True
            )
            return

        caller_channel = caller_voice_state.channel

        # Default source and destination to caller's current voice channel
        if source_c is None:
            source_c = caller_channel

        if destination_c is None:
            destination_c = caller_channel

        # Validate that either source or destination is the caller's channel
        if source_c.id != caller_channel.id and destination_c.id != caller_channel.id:
            await interaction.followup.send(
                f"❌ Either source or destination must be your current channel ({caller_channel.mention})",
                ephemeral=True
            )
            return

        # Get members in the source voice channel
        members_in_source = source_c.members

        if not members_in_source:
            await interaction.followup.send(f"❌ No one is in {source_c.mention}", ephemeral=True)
            return

        # Determine which members to move
        members_to_move = []

        if role is None and user is None:
            # If no filter specified, move everyone
            members_to_move = members_in_source
        else:
            # Filter members by role or specific user
            for member in members_in_source:

                # Check if this is the specified user
                if user is not None and member == user:
                    members_to_move.append(member)
                    continue

                # Check if member has the specified role
                if role is not None:
                    member_role_ids = {r.id for r in member.roles}
                    if role.id in member_role_ids:
                        members_to_move.append(member)

        if not members_to_move:
            await interaction.followup.send(
                f"❌ No members matching the criteria found in {source_c.mention}",
                ephemeral=True
            )
            return

        # Move the members
        moved_count = 0
        failed_count = 0

        for member in members_to_move:
            try:
                await member.move_to(destination_c)
                moved_count += 1
            except discord.Forbidden:
                failed_count += 1
            except discord.HTTPException:
                failed_count += 1

        # Send success message
        result_msg = f"✅ Moved {moved_count} member(s) from {source_c.mention} to {destination_c.mention}"
        if failed_count > 0:
            result_msg += f"\n⚠️ Failed to move {failed_count} member(s) (missing permissions)"

        await interaction.followup.send(result_msg, ephemeral=True)

    # -----------------------------
    # /sync_forum
    # -----------------------------
    @app_commands.command(
        name="sync_forum",
        description="Create VCs for all posts in a forum channel",
    )
    @app_commands.describe(
        forum="Select the forum channel to sync",
        category="Select the category where VCs will be created",
        sync_roles="Do you want the bot to auto assign roles? Default is False"
    )
    @app_commands.default_permissions(manage_channels=True, manage_roles=True)
    async def sync_forum(
        self,
        interaction: Interaction,
        forum: ForumChannel,
        category: CategoryChannel,
        sync_roles: bool = False
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        created = 0

        # Active threads
        for thread in forum.threads:
            if await ensure_vc_for_thread(guild, thread, category):
                created += 1

        # Archived threads
        async for thread in forum.archived_threads(limit=None):
            if await ensure_vc_for_thread(guild, thread, category):
                created += 1

        await interaction.followup.send(
            f"Sync complete. Created **{created}** voice channels in {category.name}.",
            ephemeral=True
        )
        if sync_roles:
            for thread in forum.threads:
                title = sanitize_name(thread.name)

                # Get the role matching the thread title
                role = discord.utils.get(guild.roles, name=title)
                print(role)
                if role is None:
                    await interaction.followup.send(
                        "VC role does not exist.",
                        ephemeral=True
                    )
                    continue

                assigned = set()
                members=[]
                temp_members=guild.fetch_members()
                async for mem in temp_members:
                    members.append(mem)
                # Scan messages in the thread
                member=None
                first_msg = await thread.fetch_message(thread.id)
                for user in first_msg.mentions:
                        if user is not None:
                            for m in members:
                                if m.name == user.name:
                                    member=m
                                    print(member)
                                    try:
                                        await member.add_roles(role)
                                        assigned.add(member.display_name)
                                    except discord.Forbidden:
                                        print(f"Cannot assign {role} to {member}")
                                    except Exception as e:
                                        print(e)

                await interaction.followup.send(
                    f"VC access granted to: {', '.join(assigned) if assigned else 'No new users.'}",
                    ephemeral=True
                )

    # ------------------------------
    # Cleanup Command
    # ------------------------------
    @app_commands.command(
        name="cleanup_forum",
        description="Delete VC channels, roles and clear forum threads"
    )
    @app_commands.describe(
        forum="select the forum channel to clear"
    )
    @app_commands.default_permissions(manage_channels=True, manage_roles=True)
    async def cleanup_forum(self, interaction: discord.Interaction, forum: discord.ForumChannel):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        deleted_roles = []
        deleted_channels = []

        for thread in forum.threads:
            role_name = sanitize_name(thread.name)
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                try:
                    await role.delete(reason="Cleanup VC Roles")
                    deleted_roles.append(role_name)
                except discord.Forbidden:
                    print(f"Cannot delete role {role_name} - check bot permissions")
                except discord.NotFound:
                    print(f"Cannot delete role {role_name} - role not found")

            vc_channel = discord.utils.get(guild.voice_channels, name=role_name)
            if vc_channel:
                try:
                    await vc_channel.delete(reason="Cleanup VC channels")
                    deleted_channels.append(vc_channel.name)
                except discord.Forbidden:
                    print(f"Cannot delete channel {vc_channel.name} - check bot permissions")
                except discord.NotFound:
                    print(f"Cannot delete channel {vc_channel.name} - channel not found")

            try:
                await thread.delete(reason="Cleanup forum threads")
            except discord.Forbidden:
                    print(f"Cannot delete thread {thread.name} - check bot permissions")
            except discord.NotFound:
                    print(f"Cannot delete thread {thread.name} - thread not found")

        await interaction.followup.send(
            f"Deleted VC channels: {', '.join(deleted_channels) if deleted_channels else 'None'}\n"
            f"Deleted roles: {', '.join(deleted_roles) if deleted_roles else 'None'}\n"
            f"Cleared all forum threads",
            ephemeral=True
        )
        print(f"Cleanup command used by {interaction.user.display_name} in {interaction.guild.name} server. Deleted channels: {deleted_channels}, Deleted roles: {deleted_roles}")

    # ------------------------------
    # Check verified command
    # ------------------------------
    @app_commands.command(
        name="check_verified",
        description="Checks if the user is verfied in multiple servers"
    )
    @app_commands.describe(
        user="Select the user",
        verified_only ="Do you want only the people that are verified in more than one server?"
    )
    @app_commands.default_permissions(administrator=True)
    async def check_verified(self,
                             interaction: discord.Interaction,
                             user: discord.User = None,
                             verified_only: bool = True
    ):
        await interaction.response.defer(ephemeral=True)

        config = load_config()
        guild_id = str(interaction.guild.id)
        guild_cfg = config.get(guild_id)
        if not guild_cfg:
            await interaction.followup.send(
                "❌ Verification system is not set up in this server.",
                ephemeral=True
            )
            return

        origin_guild_members = [user] if user else interaction.guild.members

        # Ignore bots
        origin_guild_members = [m for m in origin_guild_members if not m.bot]

        members_to_check = [user] if user else [m for m in interaction.guild.members if not m.bot]

        all_lines = []

        for member in members_to_check:
            verified_in = []
            not_verified_in = []
            not_in_server = []

            for cfg_guild_id, cfg in config.items():
                server_name = cfg.get("name", str(cfg_guild_id))
                verified_role_ids = {int(r) for r in cfg.get("verified_roles", [])}

                guild = self.bot.get_guild(int(cfg_guild_id))
                if not guild:
                    not_in_server.append(f"{server_name} (bot not present)")
                    continue

                # Fetch single member if single-user mode, otherwise use cached get_member()
                if user:
                    verified_only = False
                    try:
                        target_member = await guild.fetch_member(member.id)
                    except discord.NotFound:
                        target_member = None
                else:
                    target_member = guild.get_member(member.id)
                    if target_member is None:
                        not_in_server.append(server_name)
                        continue

                if target_member is None:
                    not_in_server.append(server_name)
                elif any(r.id in verified_role_ids for r in target_member.roles):
                    verified_in.append(server_name)
                else:
                    not_verified_in.append(server_name)

            # Build per-member line
            line = f"{member.mention}: "
            parts = []


            if verified_in:
                parts.append("✅ " + ", ".join(verified_in))
            if not_verified_in:
                parts.append("❌ " + ", ".join(not_verified_in))
            if not_in_server:
                parts.append("⚠️ " + ", ".join(not_in_server))
            line += " | ".join(parts)
            if not verified_only:
                all_lines.append(line)
            elif len(verified_in)>1:
                all_lines.append(line)

        # Batch the lines to respect Discord 2000-character limit

        batch = ""
        if len(all_lines)>0:
            for line in all_lines:
                # Reserve space for the header
                if len(HEADER) + len(batch) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                    await interaction.followup.send(
                        HEADER + batch,
                        ephemeral=True
                    )
                    batch = line + "\n"
                else:
                    batch += line + "\n"
        else:
            batch += "No verified members found in more than 1 server"

        # Send any remaining lines
        if batch:
            await interaction.followup.send(
                HEADER + batch,
                ephemeral=True
            )

        print(f"Check_verify command used by {interaction.user.display_name} in {interaction.guild.name} server")

    @app_commands.command(
        name="setup_verify",
        description="Setup verification in server"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_verify(self,interaction: discord.Interaction):
        view = SetupVerifyView()
        await interaction.response.send_message(
        "Configure verification system:",
        view=view,
        ephemeral=True
    )

        await view.wait()

        if not view.verified_roles:
            return

        cfg = {
            "name": interaction.guild.name,
            "verified_roles": [r.id for r in view.verified_roles],
            "allowed_roles": [r.id for r in view.allowed_roles],
            "guest_role": view.guest_role.id,
            "log_channel": view.log_channel.id
        }

        save_guild_config(str(interaction.guild.id), cfg)
        print(f"Verification system configured for guild {interaction.guild.name} by {interaction.user.display_name}")

    @app_commands.command(
        name="verify_user",
        description="Gives the user the verified role"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def assign_role(self,
                         interaction: discord.Interaction,
        ):
        guild_id = str(interaction.guild.id)
        guild_cfg = load_guild_config(guild_id, interaction.guild.name)

        if not guild_cfg:
            await interaction.response.send_message(
                "❌ Verification system is not set up in this server.",
                ephemeral=True
            )
            return

        view = VerifyUserView(
            invoker=interaction.user,
            guild=interaction.guild,
            config=guild_cfg
        )

        await interaction.response.send_message(
            "Select users and roles to assign:",
            view=view,
            ephemeral=True
        )

        await view.wait()
        verified_users = getattr(view, "selected_users", []) or []

        if not verified_users:
            print(f"{interaction.user.display_name} completed verification UI with no selected users in {interaction.guild.name}")
        else:
            try:
                users_text = ", ".join(u.display_name for u in verified_users)
            except Exception:
                users_text = ", ".join(getattr(u, "name", str(u)) for u in verified_users)
            print(f"{interaction.user.display_name} has verified: {users_text} in {interaction.guild.name}")

    @app_commands.command(
        name="remove_verify",
        description="Removes the verified role from a user"
    )
    @app_commands.default_permissions(manage_roles=True)
    async def remove_verify(self,
                         interaction: discord.Interaction,
        ):
        guild_id = str(interaction.guild.id)
        guild_cfg = load_guild_config(guild_id, interaction.guild.name)

        if not guild_cfg:
            await interaction.response.send_message(
                "❌ Verification system is not set up in this server.",
                ephemeral=True
            )
            return

        view = RemoveVerifyView(
            invoker=interaction.user,
            guild=interaction.guild,
            config=guild_cfg
        )

        await interaction.response.send_message(
            "Select users and roles to remove:",
            view=view,
            ephemeral=True
        )
        await view.wait()
        unverified_users = getattr(view, "selected_users", []) or []

        if not unverified_users:
            print(f"{interaction.user.display_name} completed unverification UI with no selected users in {interaction.guild.name}")
        else:
            try:
                users_text = ", ".join(u.display_name for u in unverified_users)
            except Exception:
                users_text = ", ".join(getattr(u, "name", str(u)) for u in unverified_users)
            print(f"{interaction.user.display_name} has unverified: {users_text} in {interaction.guild.name}")

    # ------------------------------
    # Send Thread Messages Command
    # ------------------------------
    @app_commands.command(
        name="create_threads",
        description="Create private threads and send custom messages to members"
    )
    @app_commands.default_permissions(manage_threads=True)
    async def create_threads(self, interaction: discord.Interaction):
        from ui import ThreadMessageView

        view = ThreadMessageView(
            invoker=interaction.user,
            guild=interaction.guild
        )

        await interaction.response.send_message(
            "Configure thread messages:",
            view=view,
            ephemeral=True
        )
    # ------------------------------
    # Raid Roles
    # ------------------------------
    @app_commands.command(
        name="setup_raid",
        description="Setup raid roles in server"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_raid(self,interaction: discord.Interaction):
        view = SetupRaidView()
        await interaction.response.send_message(
        "Configure Raid:",
        view=view,
        ephemeral=True
    )

        await view.wait()

        if not view.raid_lead_role or not view.raid_backup_role or not view.raid_scout_role:
            return

        cfg = load_guild_config(str(interaction.guild.id), str(interaction.guild.name))
        if cfg is None:
            await interaction.followup.send(
                "❌ Server not configured. Please run /setup_verify first.",
                ephemeral=True
            )
            return

        cfg.update({
            "Raid Channel": view.raid_vc_channel.id,
            "Raid roles": {
                "Lead Role": view.raid_lead_role.id,
                "Back-Up Role": view.raid_backup_role.id,
                "Scout Role": view.raid_scout_role.id
            }
        })

        save_guild_config(str(interaction.guild.id), cfg)
        print(f"Raid roles configured for guild {interaction.guild.name} by {interaction.user.display_name}")

    async def raid_moving_task(self,guild: discord.Guild, cfg : dict):
        """Background task that monitors the raid."""
        try:
            while os.path.exists(os.path.join(get_config_dir(), f"{guild.id}_raid.json")):
            # Your background task logic here
            # Example: Monitor raid status, update roles, etc.
                await asyncio.sleep(5)  # Check every 5 seconds
                if os.path.exists(os.path.join(get_config_dir(), f"{guild.id}_raid.json")):
                    membersToMove=[]
                    moved_count=0
                    failed_count=0
                    for cid in cfg["channels"]:
                        c=guild.get_channel(cid)
                        for m in c.members:
                            membersToMove.append(m)

                    for member in membersToMove:
                        try:
                            await member.move_to(guild.get_channel(cfg["Raid Channel"]))
                            moved_count += 1
                        except discord.Forbidden:
                            failed_count += 1
                        except discord.HTTPException:
                            failed_count += 1
                else:
                    print(f"raid in {guild.name} ended")



        except Exception as e:
            print(f"Raid background task error for guild {guild.id}: {e}")

    @app_commands.command(
        name="raid_start",
        description="Start a raid"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def raid_start(self, interaction: discord.Interaction):
        try:
            print(load_guild_config(str(interaction.guild.id), str(interaction.guild.name)).keys())
            rcfg= {"Raid Channel" : load_guild_config(str(interaction.guild.id), str(interaction.guild.name))["Raid Channel"],
                   "Raid roles" : load_guild_config(str(interaction.guild.id), str(interaction.guild.name))["Raid roles"]}
            if not os.path.exists(os.path.join(get_config_dir(), f"{str(interaction.guild.id)}_raid.json")):
                view = RaidStartView(
                    invoker=interaction.user,
                    guild=interaction.guild
                )
                await interaction.response.send_message(
                    view=view,
                    ephemeral=True
                )

                await view.wait()
                if not getattr(view, "confirmed", False):
                    await interaction.followup.send("Raid start cancelled.", ephemeral=True)
                    return

                if not view.channels:
                    await interaction.followup.send("Didn't select channels to pull people from")
                    return
                for m in view.lead_members:
                    await m.add_roles(interaction.guild.get_role(rcfg["Raid roles"]["Lead Role"]))
                for m in view.back_up_members:
                    await m.add_roles(interaction.guild.get_role(rcfg["Raid roles"]["Back-Up Role"]))
                for m in view.scout_members:
                    await m.add_roles(interaction.guild.get_role(rcfg["Raid roles"]["Scout Role"]))

                cfg = {
                    "name": interaction.guild.name,
                    "channels": [c.id for c in getattr(view, "channels", [])],
                    "leads": [m.id for m in getattr(view, "lead_members", [])],
                    "back_up_lead": [m.id for m in getattr(view, "back_up_members", [])],
                    "scouts": [m.id for m in getattr(view, "scout_members", [])],
                }

                if cfg["leads"]:
                    save_raid_config(str(interaction.guild.id), cfg)
                    cfg.update(rcfg)
                    # Start background task to monitor the raid
                    asyncio.create_task(self.raid_moving_task(interaction.guild,cfg))

                    await interaction.followup.send(
                        "✅ Raid started successfully! Background monitoring is now active.",
                        ephemeral=True
                    )

                else:
                    return interaction.followup.send("Failed to start.")
            else:
                await interaction.response.send_message(
                    "⚠️ A raid is already running. Please end the current raid first.",
                    ephemeral=True
                )
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Failed to start raid: {e}")

    async def load_raid(self,guild_id: str)->dict|None:
        path = os.path.join(get_config_dir(), f"{guild_id}_raid.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(e)
                return None
        return None

    @app_commands.command(
        name="raid_stop",
        description="Stop the current raid that is happening in the server"
    )
    @app_commands.describe(
        channel= "Where to move everyone when done"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def raid_stop(self, interaction: discord.Interaction,channel: discord.VoiceChannel=None):
        guild=interaction.guild
        source_channel = interaction.channel
        guild_id = str(interaction.guild.id)
        rcfg = {"Raid Channel": load_guild_config(guild_id, interaction.guild.name)["Raid Channel"],"Raid roles": load_guild_config(guild_id, interaction.guild.name)["Raid roles"]}
        crcfg= await self.load_raid(guild_id)
        await interaction.response.defer(ephemeral=True)

        if crcfg is None:
            await interaction.followup.send("No raid currently running")
        else:
            try:
                for m in crcfg["leads"]:
                    await guild.get_member(m).remove_roles(interaction.guild.get_role(rcfg["Raid roles"]["Lead Role"]))
                for m in crcfg["scouts"]:
                    await guild.get_member(m).remove_roles(interaction.guild.get_role(rcfg["Raid roles"]["Scout Role"]))
                for m in crcfg["back_up_lead"]:
                    await guild.get_member(m).remove_roles(interaction.guild.get_role(rcfg["Raid roles"]["Back-Up Role"]))
                os.remove(os.path.join(get_config_dir(), f"{guild_id}_raid.json"))
                membersToMove = []
                moved_count = 0
                failed_count = 0

                if channel is None:
                    channel = guild.get_channel(crcfg["channels"][0])
                else:
                    target_channel = channel

                membersToMove = []
                for m in source_channel.members:
                    membersToMove.append(m)
                
                for member in membersToMove:
                    try:
                        await member.move_to(target_channel)
                        moved_count += 1
                    except discord.Forbidden:
                        failed_count += 1
                    except discord.HTTPException:
                        failed_count += 1
                await interaction.followup.send("Raid Stopped")
            except Exception as e:
                await  interaction.followup.send("Failed To Stop")
                import traceback
                traceback.print_exc()
                print(e)
    # ------------------------------
    # Help Commands
    # ------------------------------

    @app_commands.command(
        name="help_verify",
        description="explains the verification commands"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def help_verify(self,interaction: discord.Interaction):
        await interaction.response.send_message(
            "Verification Commands:\n"
            "/setup_verify - Configure the verification system for this server (set verified roles, guest role, log channel)\n"
            "/verify_user - Assign the verified role to users through an interactive UI\n"
            "/remove_verify - Remove the verified role from users through an interactive UI\n"
            "/check_verified - Check which servers a user is verified in\n"
            "Note: You must run /setup_verify before using the other verification commands.",
            ephemeral=True
        )

    @app_commands.command(
        name="help_raid",
        description="explains the raid commands"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def help_raid(self,interaction: discord.Interaction):
        await interaction.response.send_message(
            "Raid Commands:\n"
            "/setup_raid - Configure the raid roles and channel for this server\n"
            "/raid_start - Start a raid by selecting channels to pull users from and assigning them roles\n"
            "/raid_stop - Stop the current raid and optionally move users back to a specified channel\n"
            "Note: You must run /setup_raid before using the other raid commands.",
            ephemeral=True
        )