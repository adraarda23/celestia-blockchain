import requests
from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, jwt_required, create_access_token,get_jwt_identity
import dotenv
import os
import json
import base64
from datetime import datetime
from database import save_game_record, get_game_record, get_last_game_id,get_player_matches


app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY")
jwt= JWTManager(app)

dotenv.load_dotenv()
KASA_ADDRESS = os.environ.get("WALLET_ADDRESS")
API_KEY = os.environ.get("API_KEY")
RPC_URL = os.environ.get("RPC_URL")
TX_STATUS_URL = os.environ.get("TX_STATUS_URL")
BLOCK_TIME_SECONDS = 5


@app.route('/protected', methods=['POST'])
@jwt_required()
def protected():
    # JWT token'ından walletAddress'ı al
    wallet_address = get_jwt_identity()
    return jsonify({
        'message': 'Access granted',
        'walletAddress': wallet_address
    })

def transfer_funds(to_address, amount):
    """
    Belirtilen adrese belirtilen miktarda transfer yapar.
    
    Args:
        to_address (str): Paranın gönderileceği adres
        amount (int/str): Gönderilecek miktar
    
    Returns:
        dict: İşlem sonucu (başarılıysa response data, başarısızsa hata mesajı)
    """
    if not to_address or not amount:
        return {"error": "Missing required parameters"}

    transfer_payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "state.Transfer",
        "params": [
            to_address,
            str(amount),  # Amount'u string'e çeviriyoruz, RPC beklenti bu yönde
            {
                "gas_price": 0.002,
                "is_gas_price_set": True,
                "gas": 142225,
                "signer_address": KASA_ADDRESS,
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY
    }

    try:
        # RPC sunucusuna isteği gönder
        response = requests.post(RPC_URL, headers=headers, json=transfer_payload)
        response.raise_for_status()  # Hata varsa exception fırlatır

        # Başarılıysa yanıtı döndür
        return response.json()
    except requests.exceptions.RequestException as e:
        # Hata durumunda hata mesajını döndür
        return {"error": f"Failed to transfer: {str(e)}", "status_code": response.status_code if response else 500}

# Örnek Kullanım: Kazananın ödülünü teslim etme
def deliver_prize(winner_address, prize_amount=100):
    """
    Kazanan oyuncuya ödül teslim eder.
    
    Args:
        winner_address (str): Kazananın adresi
        prize_amount (int): Ödül miktarı (varsayılan 100)
    """
    result = transfer_funds(winner_address, prize_amount)
    if "error" in result:
        print(f"Ödül teslim edilemedi: {result['error']}")
    else:
        print(f"Ödül başarıyla teslim edildi: {winner_address} adresine {prize_amount} gönderildi")
        print(f"Detaylar: {result}")


def verify_transaction(tx_hash, max_age_seconds=120):
    """
    Verilen tx_hash'in geçerli ve son 1 dakika içinde gerçekleşmiş bir işlem olup olmadığını kontrol eder.
    """
    if not tx_hash or not tx_hash.startswith("0x"):
        return False, "Geçersiz tx_hash formatı"

    url = f"{TX_STATUS_URL}?hash={tx_hash}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "result" not in data:
            return False, "RPC yanıtı beklenen formatta değil"

        result = data["result"]

        is_committed = result.get("status") == "COMMITTED"
        if not is_committed:
            return False, f"İşlem COMMITTED değil, mevcut durum: {result.get('status', 'Bilinmiyor')}"

        current_height = get_current_block_height()
        tx_height = int(result.get("height", 0))
        
        if current_height is None:
            return False, "COMMITTED işlem doğrulandı (zaman kontrolü yapılamadı)"

        block_age = current_height - tx_height
        if block_age < 0:
            return False, "Geçersiz blok yüksekliği (gelecekte bir işlem?)"

        age_in_seconds = block_age * BLOCK_TIME_SECONDS
        if age_in_seconds > max_age_seconds:
            return False, f"İşlem son 1 dakikada gerçekleşmedi, yaşı: {age_in_seconds} saniye"

        return True, f"COMMITTED işlem doğrulandı, yaşı: {age_in_seconds} saniye (son 2 dakika içinde)"

    except requests.exceptions.RequestException as e:
        return False, f"RPC isteği başarısız: {str(e)}"
    except ValueError as e:
        return False, f"Blok yüksekliği parse hatası: {str(e)}"

def get_current_block_height():
    """
    Mevcut blok yüksekliğini alır (varsayımsal endpoint).
    """
    try:
        response = requests.get("https://rpc-mocha.pops.one/block", timeout=10)
        response.raise_for_status()
        data = response.json()
        return int(data["result"]["block"]["header"]["height"])
    except:
        return None

@app.route('/verify_transfer', methods=['POST'])
def verify_tx():
    """
    Front-end'den gelen tx_hash'i doğrular ve True/False döner.
    """
    data = request.get_json()
    tx_hash = data.get('tx_hash')

    if not tx_hash:
        return jsonify({"valid": False, "message": "tx_hash parametresi eksik"}), 400

    is_valid, message = verify_transaction(tx_hash)
    return jsonify({
        "valid": is_valid,
        "message": message
    }), 200

def create_game_data(players, bet_amount, scores, winner, questions, timestamp=None):
    if not isinstance(players, list) or len(players) < 2:
        raise ValueError("players en az 2 oyuncudan oluşan bir liste olmalı")
    if not isinstance(bet_amount, (int, float)) or bet_amount < 0:
        raise ValueError("bet_amount pozitif bir sayı olmalı")
    if not isinstance(scores, dict) or len(scores) != len(players):
        raise ValueError("scores, tüm oyuncular için bir sözlük olmalı")
    
    standardized_players = []
    player_wallets = []
    for p in players:
        if isinstance(p, str):
            standardized_players.append({"wallet": p})
            player_wallets.append(p)
        elif isinstance(p, dict) and "wallet" in p:
            standardized_players.append({"wallet": p["wallet"]})
            player_wallets.append(p["wallet"])
        else:
            raise ValueError("players listesi string veya {'wallet': '...'} formatında olmalı")
    
    if winner not in player_wallets:
        raise ValueError("winner, oyuncular arasında olmalı")
    
    if not isinstance(questions, list) or len(questions) == 0:
        raise ValueError("questions dolu bir liste olmalı")

    if timestamp is None:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    else:
        try:
            datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("timestamp formatı 'YYYY-MM-DD HH:MM:SS' olmalı")

    standardized_questions = []
    for q in questions:
        if not all(k in q for k in ["question", "answers", "correct"]):
            raise ValueError("Her soruda 'question', 'answers' ve 'correct' olmalı")
        standardized_questions.append({
            "question": q["question"],
            "answers": q["answers"],
            "correct": q["correct"]
        })

    game_id = get_last_game_id() + 1

    game_data = {
        "game_id": game_id,
        "players": standardized_players,
        "bet_amount": bet_amount,
        "scores": scores,
        "winner": winner,
        "timestamp": timestamp,
        "questions": standardized_questions
    }
    return game_data

def save_records(namespace, game_data, wallet_address):
    if not namespace or not game_data or not wallet_address:
        return {"error": "Eksik parametre: namespace, game_data, wallet_address gerekli"}

    try:
        game_json = json.dumps(game_data)
        base64_data = base64.b64encode(game_json.encode()).decode()
    except Exception as e:
        return {"error": "Game data encode edilemedi", "message": str(e)}

    headers = {"Content-Type": "application/json", "x-api-key": API_KEY}
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "blob.Submit",
        "params": [
            [{"namespace": namespace, "data": base64_data}],
            {"gas_price": 0.002, "is_gas_price_set": True, "signer_address": wallet_address}
        ]
    }

    try:
        response = requests.post(RPC_URL, json=payload, headers=headers)
        if response.status_code != 200:
            return {"error": "Blob gönderimi başarısız", "details": response.json()}

        result = response.json()
        block_height = result.get("result")

        player1_wallet = game_data["players"][0]["wallet"]
        player2_wallet = game_data["players"][1]["wallet"]

        record_id = save_game_record(player1_wallet, player2_wallet, block_height, namespace)
        if not record_id:
            return {"error": "Veritabanına kayıt başarısız"}

        return {
            "message": "Blob submitted successfully",
            "block_height": block_height,
            "namespace": namespace,
            "game_id": record_id
        }
    except requests.exceptions.RequestException as e:
        return {"error": "İstek başarısız", "message": str(e)}

def fetch_blob_game_data(block_height, namespace):
    """Belirli bir block_height ve namespace ile blob'dan game_data'yı çeker."""
    headers = {"Content-Type": "application/json", "x-api-key": API_KEY}
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": "blob.GetAll",  # blob.Get yerine blob.GetAll kullanıyoruz
        "params": [block_height, [namespace]]
    }

    try:
        response = requests.post(RPC_URL, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"Blob.GetAll isteği başarısız: {response.status_code}, {response.text}")
            return None
        
        data = response.json()
        if "result" not in data or not isinstance(data["result"], list) or len(data["result"]) == 0:
            print(f"Geçersiz yanıt: {data}")
            return None
        
        # İlk blob'un verisini al ve decode et
        blob_data = data["result"][0].get("data", "")
        if not blob_data:
            print("Blob'da data alanı bulunamadı")
            return None
        
        # Base64'ten JSON'a çevir
        decoded_base64 = base64.b64decode(blob_data).decode("utf-8")
        game_data = json.loads(decoded_base64)
        return game_data

    except requests.exceptions.RequestException as e:
        print(f"Blob çekme hatası: {e}")
        return None
    except (base64.binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"Blob decode hatası: {e}")
        return None

@app.route('/get_game_record/<int:game_id>', methods=['GET'])
@jwt_required()
def get_game(game_id):
    record = get_game_record(game_id)
    if not record:
        return jsonify({"error": "Oyun kaydı bulunamadı"}), 404

    game_data = fetch_blob_game_data(record["block_height"], record["namespace"])
    if game_data:
        return jsonify(game_data), 200
    return jsonify({"error": "Blob verisi alınamadı", "record": record}), 500

@app.route('/get_player_history', methods=['GET'])
@jwt_required()
def get_player_history():
    current_user = get_jwt_identity()
    try:
        matches = get_player_matches(current_user)
        history = [{
            "game_id": match[0],
            "player1": match[1],
            "player2": match[2],
            "block_height": match[3],
            "namespace": match[4],
            "is_player1": match[1] == current_user
        } for match in matches]
        
        return jsonify({"matches": history}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    #deliver_prize("celestia13jncmr6fujd7l6m67y874p4kqpmfxa7ugys5vc")
    app.run(debug=True,port=5001)
