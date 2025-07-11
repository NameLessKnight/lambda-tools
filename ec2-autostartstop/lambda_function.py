# MIT License
# Copyright (c) 2025 Wang Qiang
# Source: https://github.com/NameLessKnight/lambda-tools

import boto3
import urllib.request
import json
import logging
from datetime import datetime, timedelta, timezone

# ログ設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = 'ap-northeast-1'
ec2_client = boto3.client('ec2', region_name=REGION)
rds_client = boto3.client('rds', region_name=REGION)

# 日本標準時（JST: UTC+9）
JST = timezone(timedelta(hours=9))
BASE_HOLIDAY_API_URL = "https://holidays-jp.github.io/api/v1/{year}/date.json"

def lambda_handler(event, context):
    try:
        # 現在時刻に基づきデフォルトのアクション（startまたはstop）を決定
        default_action = determine_action()
         # 日本の祝日を考慮して、休日の場合はstopを無効にする

        if is_japan_holiday():
            logger.info("今日は日本の祝日です。stopだけ実行する。")
            default_action = "stop"  # 祝日はstopだけ実行する

        # targetは"ec2"、"rds"、"all"のいずれか
        target = event.get('target', 'all')
        logger.info(f"時間ベースで決定されたデフォルトアクション: {default_action}, 対象: {target}")

        if target in ['ec2', 'all']:
            manage_ec2_instances(default_action)
    except Exception as e:
        logger.error(f"処理に失敗しました: {e}")

def determine_action():
    """
    6～18はstart、それ以外の時間帯はstopをデフォルトアクションとする
    """
    hour = datetime.now(JST).hour
    return 'start' if 8 <= hour < 18 else 'stop'
def is_japan_holiday():
    """ 今日が祝日かどうかを判断する """
    today = datetime.now(JST)
    
    # 日本の祝日を取得する
    holidays = get_japan_holidays()
    
    # 今日が祝日かどうかを確認
    if today.strftime('%Y-%m-%d') in holidays:
        logger.info(f"今日は祝日です: {holidays[today.strftime('%Y-%m-%d')]}")
        return True
    # 今日が週末かどうかを確認（土曜日または日曜日）
    elif today.weekday() >= 5:  # 5は土曜日、6は日曜日
        logger.info("今日は週末です（土曜日または日曜日）")
        return True
    
    return False
    
def get_japan_holidays():
    """ 日本の祝日リストを取得する（動的な年を使用）"""
    year = datetime.now(JST).year  # 現在の年を動的に取得
    holiday_url = BASE_HOLIDAY_API_URL.format(year=year)
    try:
        with urllib.request.urlopen(holiday_url) as response:
            data = response.read().decode('utf-8')
            holidays_data = json.loads(data)
            
            holidays = list(holidays_data.keys())
            
            logger.info(f"{year}年の日本の祝日: {holidays}")
            return holidays
    except Exception as e:
        logger.error(f"日本の祝日情報を取得できませんでした: {e}")
        return []
    
def manage_ec2_instances(default_action):
    """ タグと現在時刻に従ってEC2インスタンスを起動/停止 """
    instances_info = get_ec2_instances_with_tag('autostartstop')
    if not instances_info:
        logger.info("対象のEC2インスタンスが見つかりません")
        return

    for instance_id, tag_value, all_tags in instances_info:
        logger.info(f"EC2インスタンス: {instance_id}, タグ値: {tag_value}, 全タグ: {all_tags}, 時間ベースのアクション: {default_action}")
        if should_start(tag_value, default_action):
            start_instances(ec2_client, [instance_id], "EC2", all_tags)
        elif should_stop(tag_value, default_action):
            stop_instances(ec2_client, [instance_id], "EC2", all_tags)
        else:
            logger.info(f"{instance_id} tag_value:{tag_value} default_action:{default_action} タグと時間が一致しないため、操作は行いません")

def get_ec2_instances_with_tag(tag_key):
    """ 指定タグキーを持つEC2インスタンスとそのタグ値、全タグを取得 """
    filters = [
        {'Name': 'tag-key', 'Values': [tag_key]},
        {'Name': 'instance-state-name', 'Values': ['stopped', 'running']}
    ]
    try:
        response = ec2_client.describe_instances(Filters=filters)
        instances_info = []
        for r in response['Reservations']:
            for i in r['Instances']:
                tags = {t['Key']: t['Value'] for t in i.get('Tags', [])}
                tag_value = tags.get(tag_key)
                if tag_value:
                    instances_info.append((i['InstanceId'], tag_value, tags))
        logger.info(f"対象のEC2インスタンス: {instances_info}")
        return instances_info
    except Exception as e:
        logger.error(f"EC2インスタンスの取得に失敗しました: {e}")
        return []

def should_start(tag_value, default_action):
    """
    起動を実行すべきか判定する関数：
    - default_actionが"start"の場合、tagが"true"または"start"なら起動
    - それ以外は起動しない
    """
    if default_action == "start":
        return tag_value in ["true", "start", "auto"]
    return False

def should_stop(tag_value, default_action):
    """
    停止を実行すべきか判定する関数：
    - default_actionが"stop"の場合、tagが"true"または"stop"なら停止
    - それ以外は停止しない
    """
    if default_action == "stop":
        return tag_value in ["true", "stop", "auto"]
    return False

def start_instances(client, ids, resource_type, tags):
    logger.info(f"{resource_type}インスタンス起動処理: {ids}, タグ: {tags}")
    try:
        response = client.start_instances(InstanceIds=ids)
        logger.info(f"{resource_type}インスタンスの起動に成功しました: {response}")
    except Exception as e:
        logger.error(f"{resource_type}インスタンスの起動に失敗しました: {e}")

def stop_instances(client, ids, resource_type, tags):
    logger.info(f"{resource_type}インスタンス停止処理: {ids}, タグ: {tags}")
    try:
        response = client.stop_instances(InstanceIds=ids)
        logger.info(f"{resource_type}インスタンスの停止に成功しました: {response}")
    except Exception as e:
        logger.error(f"{resource_type}インスタンスの停止に失敗しました: {e}")
