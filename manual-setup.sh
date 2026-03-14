#!/bin/bash
# Manual setup: run the exact sequence from the original spec.
# Run as root: sudo bash manual-setup.sh
# Use this on a fresh Debian/Ubuntu box when you want the classic fixed server list (no config file).

set -eu

if [ "$(id -u)" -ne 0 ]; then
	echo "Run as root: sudo $0"
	exit 1
fi

echo "=== Installing Ookla repo and packages ==="
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
# Ubuntu 24.04 (noble): use jammy repo if noble has no Release file
[ -f /etc/apt/sources.list.d/ookla_speedtest-cli.list ] && grep -q noble /etc/apt/sources.list.d/ookla_speedtest-cli.list 2>/dev/null && \
	sed -i 's/noble/jammy/g' /etc/apt/sources.list.d/ookla_speedtest-cli.list
apt-get update -qq
apt-get install -y speedtest iperf3 mtr jq

echo "=== Accepting Ookla license ==="
speedtest --accept-license --accept-gdpr || true

echo "=== Optional: crontab alias and root crontab template ==="
# Alias for the user who ran sudo (so they can use nano for crontab -e)
if [ -n "${SUDO_USER:-}" ] && [ -d "/home/$SUDO_USER" ]; then
	grep -q "EDITOR=nano crontab" "/home/$SUDO_USER/.bash_aliases" 2>/dev/null || \
		echo -e "alias crontab='EDITOR=nano crontab'" >> "/home/$SUDO_USER/.bash_aliases"
fi
# Root crontab template (use netperf-scheduler start to add the actual netperf cron line)
cat > /tmp/root-crontab-template << 'CRONEOF'
SHELL=/bin/bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin

# Example of job definition:
# .---------------- minute (0 - 59) or every number of minutes (*/n)
# |  .------------- hour (0 - 23) or every number of minutes (*/n)
# |  |  .---------- day of month (1 - 31)
# |  |  |  .------- month (1 - 12) OR jan,feb,mar,apr ...
# |  |  |  |  .---- day of week (0 - 6) (Sunday=0 or 7) OR sun,mon,tue,wed,thu,fri,sat
# *  *  *  *  * user-name  command to be executed
CRONEOF
echo "Crontab template saved to /tmp/root-crontab-template."

echo "=== Installing netperf-scheduler, netperf-tester, netperf-reporter to /bin ==="
TAB="$(printf '\t')"

# netperf-scheduler
cat > /bin/netperf-scheduler << 'SCRIPT1'
#!/bin/bash
set -eu

### Root check ###
if [ "$(id -u)" -ne 0 ]; then
TABecho -e "\nMUST BE RUN AS ROOT!\n"; exit 1
fi

### Variables ###
START_DATE="$(date +%Y%m%d)"
STORAGE_LOCATION="/var/log/netperf/$START_DATE"
CRON_JOB="5 * * * * /bin/netperf-tester $STORAGE_LOCATION"

### Process input options ###
process_arguments() {
TABif [ -z "${1:-}" ]; then
TABTABecho -e "\nIncorrect input.\n"; HELP ; exit 1
TABfi

TABcase "$1" in
TABTAB-h|help|-help|--help|/?) HELP; exit 0;;
TABTABstart|-start|--start) START;;
TABTABstop|-stop|--stop) STOP;;
TABTAB*) echo -e "\nIncorrect input.\n"; HELP; exit 1;;
TABesac
}

### Help subroutine ###
HELP() {
TABecho -e "Script to enable/disable automated and logged speed testing."
TABecho -e "\nSyntax: netperf-scheduler [start|stop|h]"
TABecho -e "options:"
TABecho -e "\tstart\tStart speed test logging"
TABecho -e "\tstop\tStop the speed test logging"
TABecho -e "\th\t\tShow this help."
TABecho
}

### Start subroutine ###
START() {
TABif crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -q "netperf"; then
TABTABecho -e "\nnetperf is already scheduled.\n"
TABTABecho -e "\nRun 'netperf-scheduler stop' before starting again.\n"
TABTABexit 1
TABfi

TABmkdir -p "$STORAGE_LOCATION"
TAB(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
TABsystemctl restart cron.service 2>/dev/null || true
TABsystemctl restart crond.service 2>/dev/null || true
TABecho -e "\nnetperf scheduled successfully.\n"
}

### Stop subroutine ###
STOP() {
TAB(crontab -l 2>/dev/null | sed '/netperf/d' || true) | crontab -
TABsystemctl restart cron.service 2>/dev/null || true
TABsystemctl restart crond.service 2>/dev/null || true
TABecho -e "\nnetperf schedule removed.\n"
}

process_arguments "$@"
SCRIPT1

# netperf-tester (fixed servers: local + 10171,53398,58326,8864 + iperf to 9000.mtu.he.net)
cat > /bin/netperf-tester << 'SCRIPT2'
#!/bin/bash
set -eu

### Root check ###
if [ "$(id -u)" -ne 0 ]; then
TABecho -e "\nMUST BE RUN AS ROOT!\n"; exit 1
fi

### Variables ###
STORAGE_LOCATION="${1}"

### Process input options ###
process_arguments() {
TABif [ -z "$1" ]; then
TABTABecho -e "\nIncorrect input.\n"; HELP ; exit 1;
TABfi

TABwhile [ -n "$1" ]; do
TABTABcase $1 in
TABTABTAB-h|help|-help|--help|/?) HELP ; exit 0;;
TABTABesac
TABTABSTART
TABdone
}

### Help subroutine ###
HELP() {
TABecho -e "Script to run the netperf programs iPerf and Ookla Speedtest CLI."
TABecho -e "\nSyntax: netperf-tester [STORAGE_LOCATION|h]"
TABecho -e "options:"
TABecho -e "h\t\tShow this help."
TABecho
}

### Start subroutine ###
START() {
TABspeedtest -f json >> "$STORAGE_LOCATION/0_speedtest-local" && sleep 10
TABspeedtest -s 10171 -f json >> "$STORAGE_LOCATION/1_speedtest-fl" && sleep 10
TABspeedtest -s 53398 -f json >> "$STORAGE_LOCATION/2_speedtest-il" && sleep 10
TABspeedtest -s 58326 -f json >> "$STORAGE_LOCATION/3_speedtest-nc" && sleep 10
TABspeedtest -s 8864 -f json >> "$STORAGE_LOCATION/4_speedtest-wa" && sleep 10
TABiperf3 --timestamp -c 9000.mtu.he.net -P 1 >> $STORAGE_LOCATION/iperf-single-stream.txt && sleep 10
TABiperf3 --timestamp -c 9000.mtu.he.net -P 8 >> $STORAGE_LOCATION/iperf-multi-stream.txt && sleep 10
TABiperf3 --timestamp -c 9000.mtu.he.net -u -b 1G >> $STORAGE_LOCATION/iperf-udp.txt
TABexit 0
}

process_arguments "$@"
START
SCRIPT2

# netperf-reporter (fixed LOCATIONS: LOCAL FL IL NC WA)
cat > /bin/netperf-reporter << 'SCRIPT3'
#!/bin/bash
set -euo pipefail

### Root check ###
if [ "$(id -u)" -ne 0 ]; then
TABecho -e "\nMUST BE RUN AS ROOT!\n"; exit 1
fi

### Variables ###
TEST_TYPE="${1:-}"
STORAGE_LOCATION="${2:-}"
STORAGE_LOCATION="${STORAGE_LOCATION%/}"
REPORT_DATE="$(date +%Y%m%d)"
LOCATIONS=(LOCAL FL IL NC WA)

### Process input options ###
process_arguments() {
TABif [ -z "${TEST_TYPE:-}" ] || [ -z "${STORAGE_LOCATION:-}" ]; then
TABTABecho -e "\nIncorrect input.\n"; HELP; exit 1
TABfi

TABcase "$TEST_TYPE" in
TABTAB-h|help|-help|--help|/?) HELP; exit 0;;
TABTAB-s|speedtest|-speedtest|--speedtest) REPORT_SPEEDTEST;;
TABTAB-i|iperf|-iperf|--iperf) REPORT_IPERF;;
TABTAB*) echo -e "\nIncorrect input.\n"; HELP; exit 1;;
TABesac
}

### Help subroutine ###
HELP() {
TABecho -e "Script to parse and combine output from netperf tests."
TABecho -e "\nSyntax: netperf-reporter [speedtest|iperf] [STORAGE_LOCATION]"
TABecho -e "options:"
TABecho -e "\tspeedtest\tGenerate a report from speedtest data"
TABecho -e "\tiperf\t\tGenerate a report from iperf data"
TABecho -e "\th\t\tShow this help."
TABecho
}

### Speedtest report subroutine ###
REPORT_SPEEDTEST() {

TABif [ ! -d "$STORAGE_LOCATION" ]; then
TABTABecho -e "ERROR: STORAGE_LOCATION does not exist: $STORAGE_LOCATION\n"; exit 1
TABfi

TABBASE_OUTFILE="$STORAGE_LOCATION/netperf-report-$REPORT_DATE"
TABCOUNTER=1
TABwhile :; do
TABTABOUTFILE=$(printf "%s_%02d.csv" "$BASE_OUTFILE" "$COUNTER")
TABTAB[ ! -e "$OUTFILE" ] && break
TABTABCOUNTER=$((COUNTER + 1))
TABdone

TABif ! command -v jq >/dev/null 2>&1; then
TABTABecho -e "ERROR: jq is required but not found in PATH.\n"; exit 1
TABfi

TABshopt -s nullglob
TABspeedtest_files=("$STORAGE_LOCATION"/[0-9]_speedtest-*)
TABshopt -u nullglob

TABif [ "${#speedtest_files[@]}" -eq 0 ]; then
TABTABecho -e "Speedtest files not in selected directory\n"; exit 1
TABfi

TABHEADER="\"hour\""
TABCOLS="\"hour\""

TABfor loc in "${LOCATIONS[@]}"; do
TABTABHEADER+=",\"\",\"${loc}_server_id\",\"${loc}_latency_ms\",\"${loc}_download_bps\",\"${loc}_upload_bps\""
TABTABCOLS+=",\"${loc}_server_id\",\"${loc}_latency_ms\",\"${loc}_download_bps\",\"${loc}_upload_bps\""
TABdone

TABprintf "%s\n" "$HEADER" > "$OUTFILE"

TAB(
TABTABfor f in "${speedtest_files[@]}"; do

TABTABTAB[ -f "$f" ] || continue

TABTABTABloc="$(basename "$f" \
TABTABTABTAB| sed -E 's/^[0-9]+_speedtest-([A-Za-z0-9]+).*$/\1/' \
TABTABTABTAB| tr '[:lower:]' '[:upper:]')"

TABTABTABjq -c --arg loc "$loc" '
TABTABTABTABselect(.type == "result")
TABTABTABTAB| {
TABTABTABTABTABloc: $loc,
TABTABTABTABTABTABts: .timestamp,
TABTABTABTABTABTABhour: (.timestamp
TABTABTABTABTABTABTAB| sub("T"; " ")
TABTABTABTABTABTABTAB| sub(":[0-9]{2}:[0-9]{2}Z$"; ":00")
TABTABTABTABTABTAB),
TABTABTABTABTABTABserver_id: (
TABTABTABTABTABTABTAB(.server.id // "ND" | tostring)
TABTABTABTABTABTABTAB+ " "
TABTABTABTABTABTABTAB+ (.server.name // "ND" | tostring)
TABTABTABTABTABTABTAB+ " "
TABTABTABTABTABTABTAB+ (.server.location // "ND" | tostring)
TABTABTABTABTABTAB),
TABTABTABTABTABTABlatency_ms: (.ping.latency // null),
TABTABTABTABTABTABdownload_bps: ((.download.bandwidth // 0) * 8),
TABTABTABTABTABTABupload_bps: ((.upload.bandwidth // 0) * 8)
TABTABTABTABTAB}
TABTABTAB' "$f"

TABTABdone
TAB) | jq -sr --argjson cols "[$COLS]" '

TABTABdef chunk($n):
TABTABTAB[range(0; length; $n) as $i | .[$i:($i+$n)]];

TABTABsort_by(.ts)
TABTAB| group_by([.hour, .loc])
TABTAB| map(.[-1])
TABTAB| sort_by(.hour)
TABTAB| group_by(.hour)
TABTAB| map(
TABTABTAB{hour: .[0].hour}
TABTABTAB+ (reduce .[] as $r ({}; . + {
TABTABTABTAB($r.loc + "_server_id"): $r.server_id,
TABTABTABTAB($r.loc + "_latency_ms"): $r.latency_ms,
TABTABTABTAB($r.loc + "_download_bps"): $r.download_bps,
TABTABTABTAB($r.loc + "_upload_bps"): $r.upload_bps
TABTABTAB}))
TABTAB)
TABTAB| .[]
TABTAB| . as $row
TABTAB| (
TABTABTAB[ $row.hour ]
TABTABTAB+ (
TABTABTABTAB($cols[1:] | chunk(4))
TABTABTABTAB| map([""] + [ .[] as $c | ($row[$c] // "ND") ])
TABTABTABTAB| add
TABTABTAB)
TABTAB)
TABTAB| map(tostring)
TABTAB| @csv

TAB' >> "$OUTFILE"

TABecho -e "\nSpeedtest report generated: $OUTFILE\n"
TABtail -n +2 $OUTFILE
}

### iperf report subroutine ###
REPORT_IPERF() {
TABecho -e "\niperf reporting not implemented yet\n"
}

process_arguments "$@"
SCRIPT3

# Replace literal "TAB" in the heredoc output with a real tab (the heredocs above use TAB as placeholder)
sed -i "s/TAB/$TAB/g" /bin/netperf-scheduler /bin/netperf-tester /bin/netperf-reporter
chmod 755 /bin/netperf-scheduler /bin/netperf-tester /bin/netperf-reporter

mkdir -p /var/log/netperf
echo ""
echo "Done. To begin a testing session:  sudo netperf-scheduler start"
echo "To terminate a testing session:    sudo netperf-scheduler stop"
echo "Report speedtest for a day:       sudo netperf-reporter -s /var/log/netperf/YYYYMMDD"
