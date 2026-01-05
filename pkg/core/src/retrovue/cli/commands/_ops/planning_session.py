"""
Planning Session REPL for interactive SchedulePlan building.

This module implements the REPL (Read-Eval-Print Loop) for the `plan build` command,
allowing operators to interactively create and edit SchedulePlans.
"""

from __future__ import annotations

import shlex

from sqlalchemy.orm import Session


class PlanningSession:
    """Interactive REPL session for building SchedulePlans."""

    def __init__(
        self,
        db: Session,
        channel_id: str,
        plan_id: str,
        plan_name: str,
    ):
        """Initialize planning session.

        Args:
            db: Database session (not committed until save)
            channel_id: Channel identifier
            plan_id: Plan ID (UUID string)
            plan_name: Plan name for prompt display
        """
        self.db = db
        self.channel_id = channel_id
        self.plan_id = plan_id
        self.plan_name = plan_name
        self.has_unsaved_changes = False

    def get_prompt(self) -> str:
        """Get the REPL prompt string."""
        return f"(plan:{self.plan_name})> "

    def run(self) -> int:
        """Run the REPL loop.

        Returns:
            Exit code (0 for success, 1 for error)
        """
        print(f"Entering planning mode for plan '{self.plan_name}'.")
        print("Type 'help' for available commands, 'save' to save and exit, 'discard' to cancel.")
        print()

        try:
            while True:
                try:
                    line = input(self.get_prompt()).strip()
                    if not line:
                        continue

                    parts = shlex.split(line)
                    if not parts:
                        continue

                    command = parts[0].lower()
                    args = parts[1:]

                    if command == "quit":
                        result = self._handle_quit()
                        if result is not None:
                            return result
                        # Continue REPL if quit was cancelled
                        continue
                    elif command == "save":
                        return self._handle_save()
                    elif command == "discard":
                        return self._handle_discard()
                    elif command == "help":
                        self._handle_help()
                    elif command == "zone":
                        self._handle_zone(args)
                    elif command == "pattern":
                        self._handle_pattern(args)
                    elif command == "program":
                        self._handle_program(args)
                    elif command == "validate":
                        self._handle_validate()
                    elif command == "preview":
                        self._handle_preview(args)
                    else:
                        print(f"Unknown command: {command}. Type 'help' for available commands.")

                except KeyboardInterrupt:
                    result = self._handle_quit()
                    if result is not None:
                        return result
                    # Continue REPL if quit was cancelled
                    continue
                except EOFError:
                    result = self._handle_quit()
                    if result is not None:
                        return result
                    # Continue REPL if quit was cancelled
                    continue
                except Exception as e:
                    print(f"Error: {e}")

        except Exception as e:
            print(f"Fatal error: {e}")
            return 1

    def _handle_quit(self) -> int | None:
        """Handle quit command.
        
        Returns:
            0 if quit confirmed, None if quit cancelled (REPL continues)
        """
        if self.has_unsaved_changes:
            response = input("You have unsaved changes. Are you sure you want to quit? [y/N]: ").strip().lower()
            if response != "y":
                print("Quit cancelled.")
                return None  # Continue REPL
        print("Exiting planning mode.")
        return 0

    def _handle_save(self) -> int:
        """Handle save command."""
        try:
            self.db.commit()
            print("Plan saved successfully.")
            return 0
        except Exception as e:
            print(f"Error saving plan: {e}")
            self.db.rollback()
            return 1

    def _handle_discard(self) -> int:
        """Handle discard command."""
        self.db.rollback()
        print("All changes discarded.")
        return 0

    def _handle_help(self) -> None:
        """Handle help command."""
        print("Available commands:")
        print("  zone add <name> --from HH:MM --to HH:MM [--days MON..SUN]")
        print("  zone list")
        print("  zone show <name>")
        print("  pattern set <zone> \"<ProgramA>,<ProgramB>,...\"")
        print("  pattern weight <zone> \"<A>,<A>,<B>...\"")
        print("  pattern show <zone>")
        print("  program create <name> --type series|movie|block [--rotation random|sequential|lru] [--slot-units N]")
        print("  program list")
        print("  validate")
        print("  preview day YYYY-MM-DD")
        print("  save")
        print("  discard")
        print("  quit")
        print("  help")

    def _handle_zone(self, args: list[str]) -> None:
        """Handle zone commands."""
        if not args:
            print("Usage: zone <add|list|show> [args...]")
            return

        subcommand = args[0].lower()
        if subcommand == "add":
            self._handle_zone_add(args[1:])
        elif subcommand == "list":
            self._handle_zone_list()
        elif subcommand == "show":
            if len(args) < 2:
                print("Usage: zone show <name>")
                return
            self._handle_zone_show(args[1])
        else:
            print(f"Unknown zone command: {subcommand}")

    def _handle_zone_add(self, args: list[str]) -> None:
        """Handle zone add command."""
        # TODO: Implement zone add
        print("Zone add: Not yet implemented")
        self.has_unsaved_changes = True

    def _handle_zone_list(self) -> None:
        """Handle zone list command."""
        # TODO: Implement zone list
        print("Zone list: Not yet implemented")

    def _handle_zone_show(self, name: str) -> None:
        """Handle zone show command."""
        # TODO: Implement zone show
        print(f"Zone show '{name}': Not yet implemented")

    def _handle_pattern(self, args: list[str]) -> None:
        """Handle pattern commands."""
        if not args:
            print("Usage: pattern <set|weight|show> [args...]")
            return

        subcommand = args[0].lower()
        if subcommand == "set":
            if len(args) < 3:
                print("Usage: pattern set <zone> \"<ProgramA>,<ProgramB>,...\"")
                return
            self._handle_pattern_set(args[1], args[2])
        elif subcommand == "weight":
            if len(args) < 3:
                print("Usage: pattern weight <zone> \"<A>,<A>,<B>...\"")
                return
            self._handle_pattern_weight(args[1], args[2])
        elif subcommand == "show":
            if len(args) < 2:
                print("Usage: pattern show <zone>")
                return
            self._handle_pattern_show(args[1])
        else:
            print(f"Unknown pattern command: {subcommand}")

    def _handle_pattern_set(self, zone: str, pattern_str: str) -> None:
        """Handle pattern set command."""
        # TODO: Implement pattern set
        print(f"Pattern set for zone '{zone}': Not yet implemented")
        self.has_unsaved_changes = True

    def _handle_pattern_weight(self, zone: str, pattern_str: str) -> None:
        """Handle pattern weight command."""
        # TODO: Implement pattern weight
        print(f"Pattern weight for zone '{zone}': Not yet implemented")
        self.has_unsaved_changes = True

    def _handle_pattern_show(self, zone: str) -> None:
        """Handle pattern show command."""
        # TODO: Implement pattern show
        print(f"Pattern show for zone '{zone}': Not yet implemented")

    def _handle_program(self, args: list[str]) -> None:
        """Handle program commands."""
        if not args:
            print("Usage: program <create|list> [args...]")
            return

        subcommand = args[0].lower()
        if subcommand == "create":
            self._handle_program_create(args[1:])
        elif subcommand == "list":
            self._handle_program_list()
        else:
            print(f"Unknown program command: {subcommand}")

    def _handle_program_create(self, args: list[str]) -> None:
        """Handle program create command."""
        # TODO: Implement program create
        print("Program create: Not yet implemented")
        self.has_unsaved_changes = True

    def _handle_program_list(self) -> None:
        """Handle program list command."""
        # TODO: Implement program list
        print("Program list: Not yet implemented")

    def _handle_validate(self) -> None:
        """Handle validate command."""
        # TODO: Implement validate
        print("Validate: Not yet implemented")

    def _handle_preview(self, args: list[str]) -> None:
        """Handle preview command."""
        if not args or args[0].lower() != "day" or len(args) < 2:
            print("Usage: preview day YYYY-MM-DD")
            return
        # TODO: Implement preview day
        print(f"Preview day '{args[1]}': Not yet implemented")

