#!/bin/bash
# probe.sh <mmproj> <cap> <image> - run strata-vision alone on one GPU (engine stopped); prints peak VRAM delta + encode times.
# env: EXE=<path to strata-vision-cuda>  MODEL=<text model gguf, first split>  GPU=<nvidia-smi index>
MM=$1; CAP=$2; IMG=$3; GPU=${GPU:-0}; T=$(mktemp -d)
base=$(nvidia-smi -i $GPU --query-gpu=memory.used --format=csv,noheader,nounits)
( peak=0; while [ ! -e $T/done ]; do u=$(nvidia-smi -i $GPU --query-gpu=memory.used --format=csv,noheader,nounits); [ $u -gt $peak ] && peak=$u && echo $peak > $T/peak; sleep 0.1; done ) &
out=$(printf "ENC %s %s/o1.bin\nENC %s %s/o2.bin\nQUIT\n" $IMG $T $IMG $T | CUDA_VISIBLE_DEVICES=$GPU $EXE --mmproj $MM --model $MODEL --gpu --max-tokens $CAP 2>&1)
touch $T/done; sleep 0.3
echo "cap=$CAP peak_delta=$(( $(cat $T/peak) - base ))MiB :: $(echo "$out" | grep -E "warmed|^OK|^ERR" | tr "\n" " ")"
