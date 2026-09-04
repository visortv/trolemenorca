MENORCA BUS V10.2

CORRECCIÓN DESTINOS
-------------------
Origen y destino ahora salen de la MISMA topología.

Orden:
1. Matrices horarias válidas para la fecha.
2. Recorridos sincronizados de cada línea.
3. Extremos deducibles del nombre de línea como respaldo.

Esto evita el fallo de V10.1 donde el origen podía aparecer por fallback,
pero el destino quedaba vacío porque dependía de otra fuente.

Diagnóstico:
http://127.0.0.1:5055/api/health

Ahora debe aparecer:
topology_edges > 0

Puerto fijo: 5055.
