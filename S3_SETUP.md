# S3 Setup Guide

Guide til at konfigurere AWS S3 support i FlatGeobuf API'et.

## Forudsætninger

1. AWS konto med S3 bucket
2. IAM credentials med S3 læse-rettigheder
3. boto3 installeret: `pip install boto3`

## Trin 1: AWS Credentials

### Opret IAM bruger

1. Log ind på AWS Console
2. Gå til IAM → Users → Create user
3. Vælg "Programmatic access"
4. Attach policy: `AmazonS3ReadOnlyAccess` (eller custom policy)

### Custom IAM Policy (mere sikker)

Opret en custom policy der kun giver adgang til din bucket:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:HeadObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::your-bucket-name/*",
                "arn:aws:s3:::your-bucket-name"
            ]
        }
    ]
}
```

### Download credentials

Efter oprettelse får du:
- **Access Key ID** (f.eks. `AKIAIOSFODNN7EXAMPLE`)
- **Secret Access Key** (f.eks. `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`)

⚠️ **VIGTIGT**: Secret Access Key vises kun én gang - gem den sikkert!

## Trin 2: Upload .fgb filer til S3

### Via AWS CLI

```bash
# Installér AWS CLI hvis ikke gjort
pip install awscli

# Konfigurér credentials
aws configure

# Upload fil til S3
aws s3 cp data/rekreative_omraader.fgb s3://your-bucket-name/

# Upload flere filer
aws s3 sync data/ s3://your-bucket-name/ --exclude "*" --include "*.fgb"

# Verificér filer
aws s3 ls s3://your-bucket-name/
```

### Via AWS Console

1. Gå til S3 i AWS Console
2. Vælg din bucket
3. Klik "Upload"
4. Træk dine `.fgb` filer ind
5. Klik "Upload"

### Filstruktur i S3

Filer skal ligge i roden af bucket'en:

```
s3://your-bucket-name/
  ├── rekreative_omraader.fgb
  ├── bygninger.fgb
  └── veje.fgb
```

API'et forventer at kunne finde filen som: `s3://bucket-name/{layer_name}.fgb`

## Trin 3: Konfigurér .env

Kopiér `.env.example` til `.env`:

```bash
cp .env.example .env
```

Redigér `.env` med dine credentials:

```bash
# Logging
LOG_LEVEL=INFO

# Data source - sæt til "s3"
DATA_SOURCE=s3

# AWS S3 credentials
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=eu-west-1
S3_BUCKET_NAME=your-bucket-name
```

⚠️ **Husk**: `.env` filen er i `.gitignore` - den bliver IKKE committed til git!

## Trin 4: Test S3 connection

```bash
# Start serveren
uvicorn app:app --reload --port 8000
```

Kig efter denne linje i logs:
```
INFO - S3 data source initialiseret - bucket: your-bucket-name
```

Test med curl:

```bash
# Hent metadata
curl -I http://127.0.0.1:8000/fgb/rekreative_omraader.fgb

# Hent de første 1024 bytes
curl -H "Range: bytes=0-1023" http://127.0.0.1:8000/fgb/rekreative_omraader.fgb -o test.bin

# Verificér data
file test.bin
```

## Fejlsøgning

### "boto3 not installed"

```bash
pip install boto3
```

### "S3 credentials mangler"

Tjek at alle credentials er sat i `.env`:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `S3_BUCKET_NAME`

### "Layer not found in S3"

1. Verificér fil eksisterer i S3:
   ```bash
   aws s3 ls s3://your-bucket-name/
   ```

2. Tjek filnavn matcher layer navn:
   - URL: `/fgb/rekreative_omraader.fgb`
   - S3 key: `rekreative_omraader.fgb`

### "Access Denied" eller "403 Forbidden"

1. Tjek IAM policy giver `s3:GetObject` permission
2. Verificér credentials er korrekte
3. Tjek bucket permissions

### Debug med verbose logging

```bash
# Sæt LOG_LEVEL til DEBUG i .env
echo "LOG_LEVEL=DEBUG" >> .env

# Genstart serveren
uvicorn app:app --reload --port 8000
```

## Performance overvejelser

### S3 vs Lokal disk

**S3 fordele:**
- Ingen lokal disk storage nødvendig
- Skalérbar - kan håndtere store datasæt
- Automatisk backup og redundans
- Multi-region deployment mulig

**S3 ulemper:**
- Lidt langsommere end lokal disk (netværk latency)
- Koster penge pr. request (GET/HEAD)
- Kræver internet forbindelse

### Optimering

1. **S3 Transfer Acceleration**: Aktivér for faster uploads
   ```bash
   aws s3api put-bucket-accelerate-configuration \
       --bucket your-bucket-name \
       --accelerate-configuration Status=Enabled
   ```

2. **CloudFront**: Brug CDN foran S3 for bedre performance
   - Reducer latency
   - Reducer S3 requests (caching)

3. **Chunk size**: Standard er 64KB - kan justeres i `Config`
   ```python
   chunk_size: int = 1024 * 128  # 128 KB
   ```

## Sikkerhed

### Best practices

1. **Brug IAM roles** i stedet for access keys (EC2, ECS, Lambda)
2. **Minimer permissions** - kun GetObject på specifikke buckets
3. **Aktivér bucket versioning** for at kunne gendanne slettede filer
4. **Aktivér bucket logging** for audit trail
5. **Brug VPC endpoints** for privat S3 access (ingen internet)
6. **Roter credentials regelmæssigt**

### .env fil sikkerhed

```bash
# Sæt restriktive permissions
chmod 600 .env

# Verificér .env er i .gitignore
cat .gitignore | grep .env
```

## Miljø-specifikke configs

### Development (.env.development)

```bash
DATA_SOURCE=local
LOG_LEVEL=DEBUG
```

### Production (.env.production)

```bash
DATA_SOURCE=s3
LOG_LEVEL=WARNING
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=eu-west-1
S3_BUCKET_NAME=production-bucket
```

Brug:
```bash
# Development
cp .env.development .env
uvicorn app:app --reload --port 8000

# Production
cp .env.production .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Næste skridt

1. ✅ S3 bucket oprettet
2. ✅ IAM credentials konfigureret
3. ✅ .fgb filer uploaded
4. ✅ .env fil konfigureret
5. ✅ Server kører med S3

Nu kan du:
- Teste med OpenLayers frontend i `test_app/`
- Deploye til produktion (AWS EC2, ECS, Lambda)
- Tilføje flere data sources (Azure Blob, Google Cloud Storage)
