D=/tmp/sv1_dry_$$; L=/home/cah/r2d2/code/fpga/fable5_llm/evidence/qwen9b/bn/seedlogs_model_9b_s1_control/model_9b_s1.log
R=evidence/qwen9b/s4/S4_REPLAY.md
echo "##### GREEN: census s1 control log, today+1, s1 record"; DRYLOG=$L LOGDIR=$D/g bash evidence/qwen9b/ov/run_sv1_chip.sh model_9b_s1 model_9b_s1 control --cycles-today 196706822 --tokens-ref $R; echo "rc=$?"
echo "##### RED cycles: today = measured"; DRYLOG=$L LOGDIR=$D/r1 bash evidence/qwen9b/ov/run_sv1_chip.sh model_9b_s1 model_9b_s1 control --cycles-today 196706821 --tokens-ref $R; echo "rc=$?"
echo "##### RED tokens: s1 log judged against the s2 record"; DRYLOG=$L LOGDIR=$D/r2 bash evidence/qwen9b/ov/run_sv1_chip.sh model_9b_s1 model_9b_s2 control --cycles-today 196706822 --tokens-ref $R; echo "rc=$?"
rm -rf $D
