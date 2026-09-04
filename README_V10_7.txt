MENORCA BUS V10.7 - SINCRONIZACIÓN DIRECTA

CAMBIO DE ENFOQUE
-----------------
Se elimina la reconstrucción indirecta.

Para CADA línea:
1. Lee https://www.tmsa.es/linea/<ID>
2. Extrae Recorrido de la línea -> Sentido -> TODAS las paradas.
3. Lee https://www.tmsa.es/es/horarios/<ID>/VISIBLE/1
4. Usa exactamente esas paradas como plantilla de filas.
5. Agrupa las horas por columnas de expedición.
6. Guarda directions + blocks en data_snapshot.json.

Una línea operativa sólo se usa en la app si:
sync_complete = true
y blocks > 0.

Las líneas no operativas se guardan con su estado, pero no se ofrecen.

IMPORTANTE
----------
La web no debe abrir como "correcta" si L01 no tiene paradas+horarios.
Si la sincronización falla y no existe snapshot anterior con horarios, el
arranque termina con error en lugar de mostrar selectores vacíos.

DIAGNÓSTICO
-----------
http://127.0.0.1:5055/api/debug-blocks

Cada línea utilizable debe mostrar:
sync_complete: true
blocks: > 0

Puerto fijo: 5055.
