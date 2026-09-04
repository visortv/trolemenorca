MENORCA BUS V10.1

CORRECCIÓN:
La lista de población origen ya no depende exclusivamente de que el parser de
matrices haya asignado áreas.

Orden de obtención de poblaciones:
1. Áreas normalizadas de las matrices horarias.
2. Áreas deducidas de los recorridos sincronizados de cada línea.
3. Catálogo mínimo de poblaciones de Menorca como último respaldo para que
   la interfaz nunca arranque vacía.

Diagnóstico:
http://127.0.0.1:5055/api/health

Comprueba:
- line_count > 0
- matrix_blocks > 0 idealmente
- route_directions > 0
- route_area_count > 0

Puerto fijo: 5055
