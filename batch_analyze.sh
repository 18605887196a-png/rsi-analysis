#!/bin/bash
# 批量分析 RSI
cd "$(dirname "$0")"

CODES="159338 510300 510500 512100 159920 510900 588120 588000 159915 515080 515220 518880 512480 513180 512720 512000 512690 512170 515700 512200"

LOG="result/batch_analyze.log"
echo "开始批量分析: $(date)" > $LOG

for code in $CODES; do
    echo "=== 分析 $code ===" | tee -a $LOG
    python3 main.py $code >> $LOG 2>&1
    echo "" >> $LOG
done

echo "完成批量分析: $(date)" | tee -a $LOG