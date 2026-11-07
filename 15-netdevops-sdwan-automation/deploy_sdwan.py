import os
import urllib3
from pathlib import Path
from dotenv import load_dotenv
from netmiko import ConnectHandler
from jinja2 import Environment, FileSystemLoader
import time

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
TEMPLATE_DIR = BASE_DIR / "templates"

env = Environment(
	loader=FileSystemLoader(TEMPLATE_DIR),
	trim_blocks=True,
	lstrip_blocks=True
)
forti_parameters = {
		"device_type": "fortinet",
		"username": os.getenv("SSH_USERNAME"),
		"password": os.getenv("SSH_PASSWORD"),
		"host": "192.168.255.10"
}

def query_sdwan_health():
	print (
			f"------ Step 1: Querying Live SD-WAN Members Health Metrics ------"
			f""
		)
	try:
		with ConnectHandler(**forti_parameters) as conn:
			health_check = conn.send_command("diagnose sys sdwan health-check")
			print(health_check)
	except Exception as e:
		print(f"Try/Exception Error: {str(e)}")

def provision_sd_wan_rule():
	print(
		f"------ Step 2: Programmatically provisioning SD-WAN Service Rule via Netmiko ------"
		f""
	)
	try:
		with ConnectHandler(**forti_parameters) as conn:
			name = "VOICE-SIP-NETMIKO"
			protocol_number = "17"
			start_port = "5060"
			end_port = "5060"
			dest_address = "HQ-LAN"
			sla = "ADVPN_HEALTH"
			sla_number = "1"
			members = "3 4"

			template = env.get_template("sd-wan-variable-template.j2")
			commands = template.render(
				name=name,
				protocol_number=protocol_number,
				start_port=start_port,
				end_port=end_port,
				dest_address=dest_address,
				sla=sla,
				sla_number=sla_number,
				members=members
			).splitlines()

			conn.send_config_set(commands, read_timeout=120)

			print(f"[SUCCESS] SD-WAN Policy Successfully Configured: VOICE-LOWEST-LATENCY")
	except Exception as e:
		print(f"Try/Exception Error: {str(e)}")


def verify_sd_wan_rule():
	print(
		f"------ Step 3: Verifying installed service rule via Netmiko ------"
		f""
	)
	try:
		with ConnectHandler(**forti_parameters) as conn:
			policy = conn.send_command("diagnose sys sdwan service 10")
			if not policy.strip():
				print(f"[FAILURE] SD-WAN Rule not found in Device Configuration")
			elif "10" not in policy:
				print(f"[ERROR] Rule Number Not Found in Device Configuration")
			else:
				print(f"[VERIFIED] Rule Found in running configuration")
				print(policy)
	except Exception as e:
		print(f"Try/Exception Error: {str(e)}")

if __name__=="__main__":
	print("==================================================================")
	print("  Fortinet FortiOS REST API NetDevOps SD-WAN Automation Engine   ")
	print("==================================================================")
	query_sdwan_health()
	provision_sd_wan_rule()
	time.sleep(20)
	verify_sd_wan_rule()