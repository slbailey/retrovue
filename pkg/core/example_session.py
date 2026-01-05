#!/usr/bin/env python3
"""
Example session demonstrating RetroVue CLI usage.
This script shows how to use all the CLI commands in sequence.
"""

import subprocess
import sys
import os

def run_command(cmd, description):
    """Run a CLI command and display the result."""
    print(f"\n{'='*60}")
    print(f"COMMAND: {description}")
    print(f"{'='*60}")
    print(f"$ {cmd}")
    print("-" * 60)
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        if result.returncode != 0:
            print(f"Command failed with return code {result.returncode}")
    except Exception as e:
        print(f"Error running command: {e}")

def main():
    """Run the example session."""
    print("RetroVue Infrastructure CLI Example Session")
    print("=" * 60)
    
    # Change to the src directory to run the CLI
    os.chdir("src")
    
    # 1. Initialize the database
    run_command(
        "python -m retrovue.cli init",
        "Initialize the database"
    )
    
    # 2. Create a channel
    run_command(
        "python -m retrovue.cli channel add --name 'RetroTV' --timezone 'America/New_York' --grid-size 30 --offset 0 --rollover 60",
        "Create a channel named 'RetroTV'"
    )
    
    # 3. Create a template
    run_command(
        "python -m retrovue.cli template add --name 'Morning Show' --description 'Morning programming template'",
        "Create a template for morning programming"
    )
    
    # 4. Add blocks to the template
    run_command(
        "python -m retrovue.cli block add --template-id 1 --start '06:00' --end '09:00' --tags 'news,morning' --episode-policy 'daily'",
        "Add a morning block (6 AM - 9 AM) to the template"
    )
    
    run_command(
        "python -m retrovue.cli block add --template-id 1 --start '09:00' --end '12:00' --tags 'talk,entertainment' --episode-policy 'weekly'",
        "Add a talk show block (9 AM - 12 PM) to the template"
    )
    
    # 5. Add some assets
    run_command(
        "python -m retrovue.cli asset add --title 'Morning News' --duration 1800 --tags 'news,morning' --path '/media/morning_news.mp4' --canonical",
        "Add a canonical morning news asset (30 minutes)"
    )
    
    run_command(
        "python -m retrovue.cli asset add --title 'Weather Report' --duration 300 --tags 'news,weather' --path '/media/weather.mp4' --canonical",
        "Add a canonical weather report asset (5 minutes)"
    )
    
    run_command(
        "python -m retrovue.cli asset add --title 'Talk Show Episode 1' --duration 3600 --tags 'talk,entertainment' --path '/media/talk_show_1.mp4' --canonical",
        "Add a canonical talk show asset (60 minutes)"
    )
    
    # 6. Assign the template to the channel for a specific day
    run_command(
        "python -m retrovue.cli schedule assign --channel 'RetroTV' --template 'Morning Show' --day '2025-01-25'",
        "Assign the Morning Show template to RetroTV for January 25, 2025"
    )
    
    # 7. List assets with different filters
    run_command(
        "python -m retrovue.cli asset list --canonical-only",
        "List only canonical assets"
    )
    
    run_command(
        "python -m retrovue.cli asset list --tag 'news'",
        "List assets with 'news' tag"
    )
    
    run_command(
        "python -m retrovue.cli asset list --json",
        "List all assets in JSON format"
    )
    
    # 8. Update an asset
    run_command(
        "python -m retrovue.cli asset update --id 1 --title 'Updated Morning News' --canonical false",
        "Update asset ID 1 with new title and set canonical to false"
    )
    
    # 9. Show the updated asset list
    run_command(
        "python -m retrovue.cli asset list",
        "List all assets after update"
    )
    
    print(f"\n{'='*60}")
    print("Example session completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
