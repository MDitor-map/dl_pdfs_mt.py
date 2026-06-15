#!/bin/bash
# Script d'installation et vérification des dépendances pour dl_pdfs_mt.py
# Compatible Debian 12+ (PEP 668)

set -e  # Arrête le script en cas d'erreur

echo "=========================================="
echo " Installation des dépendances PDF Crawler"
echo "=========================================="
echo ""

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonction de vérification
check_command() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 est installé ($(command -v $1))"
        return 0
    else
        echo -e "${RED}✗${NC} $1 n'est pas installé"
        return 1
    fi
}

# 1. Vérification de Python 3
echo "[1/4] Vérification de Python 3..."
if ! check_command python3; then
    echo -e "${YELLOW}Installation de Python 3...${NC}"
    sudo apt update
    sudo apt install -y python3
fi
echo ""

# 2. Installation des dépendances via apt (méthode recommandée pour Debian 12+)
echo "[2/4] Installation des bibliothèques Python via apt..."
echo "    - python3-requests"
echo "    - python3-bs4 (BeautifulSoup4)"
echo "    - python3-tqdm"
echo ""

sudo apt update
sudo apt install -y python3-requests python3-bs4 python3-tqdm

# Vérification que les modules sont bien importables
echo ""
echo "Vérification des modules installés..."
python3 -c "import requests; print(f'  ✓ requests {requests.__version__}')" || {
    echo -e "${RED}✗ Échec de l'installation de requests${NC}"
    exit 1
}

python3 -c "import bs4; print(f'  ✓ beautifulsoup4 {bs4.__version__}')" || {
    echo -e "${RED}✗ Échec de l'installation de beautifulsoup4${NC}"
    exit 1
}

python3 -c "import tqdm; print(f'  ✓ tqdm {tqdm.__version__}')" || {
    echo -e "${RED}✗ Échec de l'installation de tqdm${NC}"
    exit 1
}

echo ""

# 3. Vérification de pip (optionnel, pour info)
echo "[3/4] Vérification de pip (optionnel)..."
if check_command pip3; then
    echo -e "${GREEN}✓${NC} pip3 est disponible (mais non utilisé pour ce script)"
else
    echo -e "${YELLOW}⚠${NC} pip3 n'est pas installé (non nécessaire pour ce script)"
fi
echo ""

# 4. Rendre le script exécutable
echo "[4/4] Configuration du script Python..."
if [ -f "dl_pdfs_mt.py" ]; then
    chmod +x dl_pdfs_mt.py
    echo -e "${GREEN}✓${NC} dl_pdfs_mt.py est maintenant exécutable"
else
    echo -e "${YELLOW}⚠${NC} dl_pdfs_mt.py non trouvé dans le répertoire courant"
    echo "   Assurez-vous que le script Python est dans le même dossier"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✓ Installation terminée avec succès !${NC}"
echo "=========================================="
echo ""
echo "Utilisation :"
echo "  ./dl_pdfs_mt.py https://exemple.com/docs -t 5 -d 3"
echo ""
echo "Options principales :"
echo "  -t, --threads    Nombre de threads (défaut: 5)"
echo "  -d, --depth      Profondeur de récursion (défaut: 3)"
echo "  -w, --wait       Délai entre requêtes (défaut: 0.5s)"
echo "  -m, --max        Nombre max de PDF à télécharger"
echo "  -o, --output     Répertoire de sortie (défaut: ./pdfs)"
echo "  --ignore-robots  Ignorer les règles robots.txt"
echo ""
