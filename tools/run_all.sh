#!/usr/bin/env bash
# Run every job to completion in ONE turn, then print one combined summary.
#
# WHY THIS EXISTS. Eighty-nine agent wake-ups in a single session produced
# nothing but "still running". Each wake reprocesses the agent's whole context,
# so for a 200k-token agent that is 200k tokens spent to say "waiting". The
# cause is serial jobs: fire one, wake, fire the next, wake.
#
#   BAD   (4 wakes, ~800k tokens of nothing)
#     run verify_ladder in background ... wake ... run verify_modal ... wake ...
#
#   GOOD  (1 wake)
#     tools/run_all.sh "verify_ladder" "verify_modal" "verify_voice --set full"
#
# Jobs run in PARALLEL by default -- they are independent simulations and the
# machine has cores. --serial runs them in order if they contend for something.
#
#   tools/run_all.sh [--serial] [--timeout SECONDS] "cmd1" "cmd2" ...
#
# Exit code is the number of failed jobs, so `&& echo ok` still works.
set -uo pipefail

SERIAL=0
TIMEOUT=""
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --serial)  SERIAL=1; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ $# -eq 0 ] && { echo "usage: run_all.sh [--serial] [--timeout S] \"cmd\" ..." >&2; exit 2; }

DIR=$(mktemp -d)
trap 'rm -rf "$DIR"' EXIT
declare -a PIDS=() CMDS=()

launch() {
  local i=$1 cmd=$2
  { if [ -n "$TIMEOUT" ]; then
      eval "timeout $TIMEOUT $cmd"
    else
      eval "$cmd"
    fi; echo $? > "$DIR/$i.rc"; } > "$DIR/$i.out" 2>&1
}

i=0
for cmd in "$@"; do
  CMDS+=("$cmd")
  if [ "$SERIAL" = 1 ]; then
    launch "$i" "$cmd"
  else
    launch "$i" "$cmd" &
    PIDS+=($!)
  fi
  i=$((i+1))
done
[ "$SERIAL" = 1 ] || wait "${PIDS[@]}" 2>/dev/null

fails=0
echo "=============================================================================="
for j in $(seq 0 $((i-1))); do
  rc=$(cat "$DIR/$j.rc" 2>/dev/null || echo "??")
  [ "$rc" = "0" ] || fails=$((fails+1))
  printf "%-4s %s\n" "$([ "$rc" = 0 ] && echo PASS || echo "FAIL($rc)")" "${CMDS[$j]}"
  # The last few lines are what carries the verdict in every verifier here.
  tail -n "${RUN_ALL_TAIL:-4}" "$DIR/$j.out" 2>/dev/null | sed 's/^/       /'
done
echo "=============================================================================="
echo "$((i-fails))/$i passed"
exit $fails
