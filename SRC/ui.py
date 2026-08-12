import discord


class ThreadMessageModal(discord.ui.Modal, title="Thread Message Configuration"):
    greeting = discord.ui.TextInput(
        label="Προσφωνηση (Greeting)",
        placeholder="e.g., Hello, Καλημέρα, etc.",
        required=True,
        max_length=100
    )

    message = discord.ui.TextInput(
        label="Message",
        placeholder="Your message here...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.greeting = self.greeting.value
        self.view.message = self.message.value
        await interaction.response.send_message(
            f"✅ Greeting and message saved!\nGreeting: {self.greeting.value}\nMessage: {self.message.value[:50]}...",
            ephemeral=True
        )


class FilteredRoleSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, role_ids: list[int], remove: bool = False):
        options = []

        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                if remove:
                    options.append(
                        discord.SelectOption(
                            label=role.name,
                            value=str(role.id),
                            description=f"Remove {role.name}"
                        )
                    )
                else:
                    options.append(
                        discord.SelectOption(
                            label=role.name,
                            value=str(role.id),
                            description=f"Assign {role.name}"
                        )
                    )

        placeholder = "Select roles to remove" if remove else "Select roles to assign"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=len(options),
            options=options
        )


class GuestRoleSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, guest_role_id: int | None, remove: bool = False):
        options = []

        if guest_role_id:
            role = guild.get_role(guest_role_id)
            if role:
                if remove:
                    options.append(
                        discord.SelectOption(
                            label=role.name,
                            value=str(role.id),
                            description="Add this role when verifying"
                        )
                    )
                else:
                    options.append(
                        discord.SelectOption(
                            label=role.name,
                            value=str(role.id),
                            description="Remove this role when verifying"
                        )
                    )

        placeholder = "Select to add guest role(optional)" if remove else "Select to remove guest role(optional)"

        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=1,
            options=options
        )


class SetupVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

        self.verified_roles = []
        self.allowed_roles = []
        self.guest_role = None
        self.log_channel = None

        # Verified roles (multi)
        self.verified_select = discord.ui.RoleSelect(
            placeholder="Select VERIFIED roles",
            min_values=1,
            max_values=5
        )
        self.verified_select.callback = self.on_verified_select
        self.add_item(self.verified_select)

        # Allowed roles (multi)
        self.allowed_select = discord.ui.RoleSelect(
            placeholder="Select ALLOWED roles",
            min_values=1,
            max_values=5
        )
        self.allowed_select.callback = self.on_allowed_select
        self.add_item(self.allowed_select)

        # Guest role (single)
        self.guest_select = discord.ui.RoleSelect(
            placeholder="Select GUEST role",
            min_values=1,
            max_values=1
        )
        self.guest_select.callback = self.on_guest_select
        self.add_item(self.guest_select)

        # Logging channel
        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Select LOGGING channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.channel_select.callback = self.on_channel_select
        self.add_item(self.channel_select)

    async def on_verified_select(self, interaction):
        self.verified_roles = self.verified_select.values
        await interaction.response.defer()

    async def on_allowed_select(self, interaction):
        self.allowed_roles = self.allowed_select.values
        await interaction.response.defer()

    async def on_guest_select(self, interaction):
        self.guest_role = self.guest_select.values[0]
        await interaction.response.defer()

    async def on_channel_select(self, interaction):
        self.log_channel = self.channel_select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        if not all([
            self.verified_roles,
            self.allowed_roles,
            self.guest_role,
            self.log_channel
        ]):
            return await interaction.response.send_message(
                "❌ Please complete all selections.",
                ephemeral=True
            )

        self.stop()
        await interaction.response.send_message(
            "✅ Setup complete!",
            ephemeral=True
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction, button):
        self.clear_items()
        self.stop()
        await interaction.response.send_message(
            "❌ Setup cancelled.",
            ephemeral=True
        )


class VerifyUserView(discord.ui.View):
    def __init__(self, invoker, guild, config: dict):
        super().__init__(timeout=300)

        self.invoker = invoker
        self.guild = guild
        self.config = config

        self.remove_guest_role = False

        self.selected_users: list[discord.Member] = []
        self.verified_roles: list[discord.Role] = []

        self.verified_role_ids = set(config.get("verified_roles", []))
        self.allowed_role_ids = set(config.get("allowed_roles", []))
        self.guest_role_id = config.get("guest_role")
        self.log_channel_id = config.get("log_channel")

        self.User_select = discord.ui.UserSelect(
            placeholder="Select users to verify",
            min_values=1,
            max_values=5
        )
        self.User_select.callback = self.on_user_select
        self.add_item(self.User_select)

        self.verified_select = FilteredRoleSelect(
            guild=self.guild,
            role_ids=self.verified_role_ids
        )
        self.verified_select.callback = self.on_verified_select
        self.add_item(self.verified_select)

        self.guest_select = GuestRoleSelect(
            guild=self.guild,
            guest_role_id=self.guest_role_id
        )
        self.guest_select.callback = self.on_guest_select
        self.add_item(self.guest_select)

    @property
    def log_channel(self) -> discord.TextChannel | None:
        if not self.log_channel_id:
            return None
        return self.guild.get_channel(self.log_channel_id)

    async def on_user_select(self, interaction):
        self.selected_users = self.User_select.values
        await interaction.response.defer()

    async def on_verified_select(self, interaction: discord.Interaction):
        self.verified_roles = [
            self.guild.get_role(int(role_id))
            for role_id in self.verified_select.values
        ]
        await interaction.response.defer()

    async def on_guest_select(self, interaction):
        self.remove_guest_role = bool(self.guest_select.values)
        await interaction.response.defer()

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):

        # Lock UI to invoker
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                "This setup is not for you.",
                ephemeral=True
            )

        if not self.selected_users or not self.verified_roles:
            return await interaction.response.send_message(
                "Select users and roles first.",
                ephemeral=True
            )

        # Allowed role check
        allowed_roles = set(self.config.get("allowed_roles", []))
        invoker_role_ids = {r.id for r in self.invoker.roles}

        if not invoker_role_ids.intersection(allowed_roles):
            return await interaction.response.send_message(
                "You are not allowed to use this command.",
                ephemeral=True
            )

        bot_member = self.guild.me
        guest_role = self.guild.get_role(self.guest_role_id)

        added = 0
        for member in self.selected_users:
            if self.remove_guest_role and guest_role and guest_role in member.roles:
                await member.remove_roles(guest_role)

            for role in self.verified_roles:
                if role < bot_member.top_role and role not in member.roles:
                    await member.add_roles(role)
                    added += 1

        await interaction.response.send_message(
            f"✅ Assigned roles to {len(self.selected_users)} user(s).",
            ephemeral=True
        )

        log_channel = self.guild.get_channel(self.log_channel_id)
        if log_channel:
            embed = discord.Embed(
                title="User Verified",
                color=discord.Color.green()
            )

            embed.add_field(
                name="Moderator",
                value=interaction.user.mention,
                inline=False
            )

            embed.add_field(
                name="Users",
                value=", ".join(u.mention for u in self.selected_users),
                inline=False
            )

            embed.add_field(
                name="Roles Assigned",
                value=", ".join(r.mention for r in self.verified_roles),
                inline=False
            )

            if self.log_channel:
                await self.log_channel.send(embed=embed)

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction, button):
        self.clear_items()
        self.stop()
        await interaction.response.send_message(
            f"❌ Verification cancelled.",
            ephemeral=True
        )


class RemoveVerifyView(discord.ui.View):
    def __init__(self, invoker, guild, config: dict):
        super().__init__(timeout=300)

        self.invoker = invoker
        self.guild = guild
        self.config = config

        self.add_guest_role = False

        self.selected_users: list[discord.Member] = []
        self.verified_roles: list[discord.Role] = []

        self.verified_role_ids = set(config.get("verified_roles", []))
        self.allowed_role_ids = set(config.get("allowed_roles", []))
        self.guest_role_id = config.get("guest_role")
        self.log_channel_id = config.get("log_channel")

        self.User_select = discord.ui.UserSelect(
            placeholder="Select users to unverify",
            min_values=1,
            max_values=5
        )
        self.User_select.callback = self.on_user_select
        self.add_item(self.User_select)

        self.verified_select = FilteredRoleSelect(
            guild=self.guild,
            role_ids=self.verified_role_ids,
            remove=True
        )
        self.verified_select.callback = self.on_verified_select
        self.add_item(self.verified_select)

        self.guest_select = GuestRoleSelect(
            guild=self.guild,
            guest_role_id=self.guest_role_id,
            remove=True
        )
        self.guest_select.callback = self.on_guest_select
        self.add_item(self.guest_select)

    @property
    def log_channel(self) -> discord.TextChannel | None:
        if not self.log_channel_id:
            return None
        return self.guild.get_channel(self.log_channel_id)

    async def on_user_select(self, interaction):
        self.selected_users = self.User_select.values
        await interaction.response.defer()

    async def on_verified_select(self, interaction: discord.Interaction):
        self.verified_roles = [
            self.guild.get_role(int(role_id))
            for role_id in self.verified_select.values
        ]
        await interaction.response.defer()

    async def on_guest_select(self, interaction):
        self.add_guest_role = bool(self.guest_select.values)
        await interaction.response.defer()

    @discord.ui.button(label="Unverify", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):

        # Lock UI to invoker
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                "This setup is not for you.",
                ephemeral=True
            )

        if not self.selected_users or not self.verified_roles:
            return await interaction.response.send_message(
                "Select users and roles first.",
                ephemeral=True
            )

        # Allowed role check
        allowed_roles = set(self.config.get("allowed_roles", []))
        invoker_role_ids = {r.id for r in self.invoker.roles}

        if not invoker_role_ids.intersection(allowed_roles):
            return await interaction.response.send_message(
                "You are not allowed to use this command.",
                ephemeral=True
            )

        bot_member = self.guild.me
        guest_role = self.guild.get_role(self.guest_role_id)

        added = 0
        for member in self.selected_users:
            if self.add_guest_role and guest_role and guest_role not in member.roles:
                await member.add_roles(guest_role)

            for role in self.verified_roles:
                if role < bot_member.top_role and role in member.roles:
                    await member.remove_roles(role)
                    added += 1

        await interaction.response.send_message(
            f"✅ Removed roles off {len(self.selected_users)} user(s).",
            ephemeral=True
        )

        log_channel = self.guild.get_channel(self.log_channel_id)
        if log_channel:
            embed = discord.Embed(
                title="User Unverified",
                color=discord.Color.green()
            )

            embed.add_field(
                name="Moderator",
                value=interaction.user.mention,
                inline=False
            )

            embed.add_field(
                name="Users",
                value=", ".join(u.mention for u in self.selected_users),
                inline=False
            )

            embed.add_field(
                name="Roles Removed",
                value=", ".join(r.mention for r in self.verified_roles),
                inline=False
            )

            if self.log_channel:
                await self.log_channel.send(embed=embed)

        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction, button):
        self.clear_items()
        self.stop()
        await interaction.response.send_message(
            f"❌ Verification cancelled.",
            ephemeral=True
        )


class ThreadMessageView(discord.ui.View):
    def __init__(self, invoker, guild):
        super().__init__(timeout=300)

        self.invoker = invoker
        self.guild = guild

        self.x_roles = []  # Roles whose members will receive threads
        self.channel = None  # Channel where threads will be created
        self.y_roles = []  # Roles to mention in messages
        self.greeting = None  # Προσφωνηση
        self.message = None  # The message content

        # X Roles selector
        self.x_roles_select = discord.ui.RoleSelect(
            placeholder="Select X roles (members to receive threads)",
            min_values=1,
            max_values=10
        )
        self.x_roles_select.callback = self.on_x_roles_select
        self.add_item(self.x_roles_select)

        # Channel selector
        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Select channel for threads",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )
        self.channel_select.callback = self.on_channel_select
        self.add_item(self.channel_select)

        # Y Roles selector
        self.y_roles_select = discord.ui.RoleSelect(
            placeholder="Select Y roles (to mention in messages)",
            min_values=1,
            max_values=10
        )
        self.y_roles_select.callback = self.on_y_roles_select
        self.add_item(self.y_roles_select)

    async def on_x_roles_select(self, interaction):
        self.x_roles = self.x_roles_select.values
        await interaction.response.send_message(
            f"✅ Selected {len(self.x_roles)} X role(s): {', '.join(r.name for r in self.x_roles)}",
            ephemeral=True
        )

    async def on_channel_select(self, interaction):
        self.channel = self.channel_select.values[0]
        await interaction.response.send_message(
            f"✅ Selected channel: {self.channel.mention}",
            ephemeral=True
        )

    async def on_y_roles_select(self, interaction):
        self.y_roles = self.y_roles_select.values
        await interaction.response.send_message(
            f"✅ Selected {len(self.y_roles)} Y role(s): {', '.join(r.name for r in self.y_roles)}",
            ephemeral=True
        )

    @discord.ui.button(label="Set Greeting & Message", style=discord.ButtonStyle.primary, row=4)
    async def set_message(self, interaction, button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                "This setup is not for you.",
                ephemeral=True
            )

        modal = ThreadMessageModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Create Threads", style=discord.ButtonStyle.green, row=4)
    async def confirm(self, interaction, button):
        # Lock UI to invoker
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                "This setup is not for you.",
                ephemeral=True
            )

        # Validate all fields are set
        if not all([self.x_roles, self.channel, self.y_roles, self.greeting, self.message]):
            return await interaction.response.send_message(
                "❌ Please complete all selections: X roles, channel, Y roles, greeting, and message.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        # Get all unique members from X roles
        members_set = set()
        for role in self.x_roles:
            members_set.update(role.members)

        # Remove bots
        members = [m for m in members_set if not m.bot]

        if not members:
            return await interaction.followup.send(
                "❌ No members found in the selected X roles.",
                ephemeral=True
            )

        # Create threads and send messages
        created_count = 0
        failed_count = 0

        for member in members:
            try:
                # Create private thread
                thread = await self.channel.create_thread(
                    name=f"Message for {member.display_name}",
                    type=discord.ChannelType.private_thread,
                    invitable=False
                )

                # Add the member to the thread
                await thread.add_user(member)

                # Build message content
                message_content = f"{self.greeting} {member.mention}\n{self.message}\n"
                for role in self.y_roles:
                    message_content += f"{role.mention}\n"

                # Send the message
                await thread.send(message_content)

                created_count += 1

            except discord.Forbidden:
                failed_count += 1
            except discord.HTTPException as e:
                print(f"Failed to create thread for {member.display_name}: {e}")
                failed_count += 1

        # Send completion message
        result_msg = f"✅ Created {created_count} thread(s) for {len(members)} member(s)"
        if failed_count > 0:
            result_msg += f"\n⚠️ Failed to create {failed_count} thread(s) (permissions or API error)"

        await interaction.followup.send(result_msg, ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, row=4)
    async def cancel(self, interaction, button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message(
                "This setup is not for you.",
                ephemeral=True
            )

        self.clear_items()
        self.stop()
        await interaction.response.send_message(
            "❌ Thread message setup cancelled.",
            ephemeral=True
        )


class SetupRaidView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.raid_lead_role = None
        self.raid_backup_role = None
        self.raid_scout_role = None
        self.raid_vc_channel=None
        self.raid_vc_channel_select = discord.ui.ChannelSelect(
            placeholder="Select Raid Voice Channel",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1
        )
        self.raid_vc_channel_select.callback = self.on_raid_vc_channel_select
        self.add_item(self.raid_vc_channel_select)
        self.raid_lead_select = discord.ui.RoleSelect(
            placeholder="Select Raid lead role",
            min_values=1,
            max_values=1
        )
        self.raid_lead_select.callback = self.on_raid_lead_select
        self.add_item(self.raid_lead_select)

        self.raid_backup_select = discord.ui.RoleSelect(
            placeholder="Select Back-up role",
            min_values=1,
            max_values=1
        )
        self.raid_backup_select.callback = self.on_backup_role_select
        self.add_item(self.raid_backup_select)

        self.raid_scout_select = discord.ui.RoleSelect(
            placeholder="Select Scout role",
            min_values=1,
            max_values=1
        )
        self.raid_scout_select.callback = self.on_scout_role_select
        self.add_item(self.raid_scout_select)

    async def on_raid_vc_channel_select(self, interaction):
        self.raid_vc_channel = self.raid_vc_channel_select.values[0] if self.raid_vc_channel_select.values else None
        await interaction.response.defer()

    async def on_raid_lead_select(self, interaction):
        self.raid_lead_role = self.raid_lead_select.values[0] if self.raid_lead_select.values else None
        await interaction.response.defer()

    async def on_backup_role_select(self, interaction):
        self.raid_backup_role = self.raid_backup_select.values[0] if self.raid_backup_select.values else None
        await interaction.response.defer()

    async def on_scout_role_select(self, interaction):
        self.raid_scout_role = self.raid_scout_select.values[0] if self.raid_scout_select.values else None
        await interaction.response.defer()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        if not all([
            self.raid_vc_channel,
            self.raid_lead_role,
            self.raid_backup_role,
            self.raid_scout_role
        ]):
            print(self.raid_vc_channel)
            print(self.raid_lead_role)
            print(self.raid_backup_role)
            print(self.raid_scout_role)
            return await interaction.response.send_message(
                "❌ Please complete all selections.",
                ephemeral=True
            )

        self.stop()
        await interaction.response.send_message(
            "✅ Setup complete!",
            ephemeral=True
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction, button):
        self.clear_items()
        self.stop()
        await interaction.response.send_message(
            "❌ Setup cancelled.",
            ephemeral=True
        )


class RaidStartView(discord.ui.View):
    def __init__(self, invoker, guild):
        super().__init__(timeout=300)
        self.confirmed = False
        self.invoker = invoker
        self.guild = guild
        self.channels= []
        self.lead_members = []
        self.back_up_members = []
        self.scout_members = []

        # Channel select
        self.channel_select = discord.ui.ChannelSelect(
            placeholder="Select channels to pull from",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=10
        )
        self.channel_select.callback = self.on_channel_select
        self.add_item(self.channel_select)

        # Lead members select
        self.lead_select = discord.ui.UserSelect(
            placeholder="Select raid lead(s)",
            min_values=1,
            max_values=5
        )
        self.lead_select.callback = self.on_lead_select
        self.add_item(self.lead_select)

        # Back-up members select
        self.backup_select = discord.ui.UserSelect(
            placeholder="Select back-up lead(s) (optional)",
            min_values=0,
            max_values=5
        )
        self.backup_select.callback = self.on_backup_select
        self.add_item(self.backup_select)

        # Scout members select
        self.scout_select = discord.ui.UserSelect(
            placeholder="Select scout(s) (optional)",
            min_values=0,
            max_values=5
        )
        self.scout_select.callback = self.on_scout_select
        self.add_item(self.scout_select)

    async def on_channel_select(self, interaction):
        self.channels = self.channel_select.values if self.channel_select.values else None
        await interaction.response.defer()

    async def on_lead_select(self, interaction):
        self.lead_members = self.lead_select.values if self.lead_select.values else []
        await interaction.response.defer()

    async def on_backup_select(self, interaction):
        self.back_up_members = self.backup_select.values if self.backup_select.values else []
        await interaction.response.defer()

    async def on_scout_select(self, interaction):
        self.scout_members = self.scout_select.values if self.scout_select.values else []
        await interaction.response.defer()

    @discord.ui.button(label="Start Raid", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        if not self.channels or not self.lead_members:
            return await interaction.response.send_message(
                "❌ Please select at least a channel and raid lead(s).",
                ephemeral=True
            )
        self.confirmed = True
        self.stop()
        await interaction.response.send_message(
            f"✅ Raid configuration complete!\n"
            f"Channels: {', '.join([channel.mention for channel in self.channels ])}\n"
            f"Leads: {', '.join([m.mention for m in self.lead_members])}\n"
            f"Back-ups: {', '.join([m.mention for m in self.back_up_members]) if self.back_up_members else 'None'}\n"
            f"Scouts: {', '.join([m.mention for m in self.scout_members]) if self.scout_members else 'None'}",
            ephemeral=True
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction, button):
        self.confirmed = False
        self.clear_items()
        self.stop()
        await interaction.response.send_message(
            "❌ Raid start cancelled.",
            ephemeral=True
        )

