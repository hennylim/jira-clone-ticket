#!/bin/bash
# Shell script to run a Python script

FILE=$(dirname "$BASH_SOURCE")/$(date +"%Y-%m-%d").check

if [ -f "$FILE" ]; then
    echo "$FILE exists. Do not run script."
else
    echo "$FILE not exists. Run script..."

    # Python 스크립트 경로 설정 (예: /home/user/my_script.py)
    python3 $(dirname "$BASH_SOURCE")/web_app.py
    script_exit_code=$?

    # 결과 출력
    echo "Python script output: $script_exit_code"

    # 종료 코드 확인 0:OK, 1:ERR
    if [ $script_exit_code -eq 0 ]; then
        echo "Python script exited normally."
    else
        echo "Python script encountered an error."
    fi
fi
