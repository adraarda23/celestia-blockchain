const express = require('express');
const jwt = require('jsonwebtoken');
const { Buffer } = require('buffer');
const Cosmos = require('@keplr-wallet/cosmos');
require("dotenv").config();

const app = express();
app.use(express.json());

const SECRET_KEY = process.env.JWT_SECRET_KEY;


// 🌟 1️⃣ Kimlik Doğrulama ve JWT Token Üretme
app.post('/auth', (req, res) => {
    const { walletAddress, signature, publicKeyBase64, message } = req.body;

    if (!walletAddress || !signature || !publicKeyBase64 || !message) {
        return res.status(400).json({ error: "Eksik veri gönderildi." });
    }

    const prefix = "celestia";  // Celestia için prefix

    // Base64 verilerini Uint8Array'e dönüştür
    const uint8Signature = new Uint8Array(Buffer.from(signature, 'base64'));
    const pubKeyUint8Array = new Uint8Array(Buffer.from(publicKeyBase64, 'base64'));

    // İmzanın geçerli olup olmadığını doğrula
    const isValid = Cosmos.verifyADR36Amino(prefix, walletAddress, message, pubKeyUint8Array, uint8Signature);

    if (!isValid) {
        return res.status(401).json({ error: "Geçersiz imza!" });
    }

    const authToken = jwt.sign(
        { sub: walletAddress, walletAddress }, // "sub" claim'i olarak walletAddress'ı ekliyoruz
        SECRET_KEY,
        { expiresIn: '1h' }
    );

    res.json({ auth_token: authToken });
});

// 🔍 2️⃣ JWT Doğrulama Endpoint’i
app.post('/verify', (req, res) => {
    const { auth_token } = req.body;

    if (!auth_token) {
        return res.status(400).json({ error: "Token eksik!" });
    }

    jwt.verify(auth_token, SECRET_KEY, (err, decoded) => {
        if (err) {
            return res.status(401).json({ error: "Geçersiz veya süresi dolmuş token!" });
        }
        res.json({ walletAddress: decoded.walletAddress, message: "Token geçerli!" });
    });
});

// Server başlat
const PORT = 3000;
app.listen(PORT, () => {
    console.log(`Auth API çalışıyor: http://localhost:${PORT}`);
});
