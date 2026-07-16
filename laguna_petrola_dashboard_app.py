import streamlit as st
import pandas as pd
import boto3
import io
import json
import uuid
import time
import altair as alt
import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr


#------------------------------------------------------------
#------------------- CONFIGURACIÓN INICIAL ------------------
#------------------------------------------------------------
st.set_page_config(
    page_title="Pétrola Dashbaord",
    page_icon="📊",       
    layout="wide",     
)

# CSS de estilos
st.markdown("""
    <style>
    /* --- PESTAÑAS --- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }

    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px;
        border-radius: 4px 4px 0 0;
        background-color: #eaf7ff;
        color: black;
        transition: color 0.2s, background-color 0.2s;
    }
            
    .stTabs [data-baseweb="tab"]:hover {
        color: red;
    }

    .stTabs [aria-selected="true"] {
        background-color: #3498db;
        color: white;
    }

    body[data-theme="dark"] .stTabs [data-baseweb="tab"] {
        color: black;
    }


    /* --- MÉTRICAS --- */
    .metric-box {
        background-color: #eaf7ff;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        margin-bottom: 15px;
    }

    .metric-value {
        font-size: 1.8rem;
        font-weight: bold;
        color: #3498db;
    }

    .metric-label {
        font-size: 0.9rem;
        color: #7f8c8d;
    }

    /* --- FILTROS --- */
    .filter-container {
        background-color: #eaf7ff;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 20px;
    }

    .filter-title {
        font-weight: bold;
        margin-bottom: 10px;
        color: #2c3e50;
    }

    /* --- MULTISELECT --- */
    .stMultiSelect [data-baseweb="tag"] {
        background-color: #3498db !important;
        color: white !important;
        border: none !important;
    }
    .stMultiSelect div[data-baseweb="select"] span {
        font-size: 14px !important;  /* Ajusta este tamaño según necesites */
    }
""", unsafe_allow_html=True)


# Para que el tab de añadir nuevos datos y revocar actualización sean rojos y esten pegados a la derecha
st.markdown("""
    <style>
        /* 1. Empujar la 5ª, 6ª y 7ª pestaña a la derecha */
        button[data-baseweb="tab"]:nth-child(5) {
            margin-left: auto !important;
        }

        /* 2. Estilo ROJO para las pestañas de ADMIN (5, 6 y 7) */
        button[data-baseweb="tab"]:nth-child(5), 
        button[data-baseweb="tab"]:nth-child(6),
        button[data-baseweb="tab"]:nth-child(7) {
            border: 1px solid #ff4b4b !important;
            border-radius: 5px 5px 0 0 !important;
            background-color: #fff5f5 !important;
            margin-right: 5px !important;
        }

        /* 3. Texto en rojo para las tres */
        button[data-baseweb="tab"]:nth-child(5) p,
        button[data-baseweb="tab"]:nth-child(6) p,
        button[data-baseweb="tab"]:nth-child(7) p {
            color: #ff4b4b !important;
            font-weight: bold !important;
        }

        /* 4. Estilo cuando alguna de las de ADMIN está seleccionada */
        button[data-baseweb="tab"]:nth-child(5)[aria-selected="true"],
        button[data-baseweb="tab"]:nth-child(6)[aria-selected="true"],
        button[data-baseweb="tab"]:nth-child(7)[aria-selected="true"] {
            background-color: #ff4b4b !important;
        }

        button[data-baseweb="tab"]:nth-child(5)[aria-selected="true"] p,
        button[data-baseweb="tab"]:nth-child(6)[aria-selected="true"] p,
        button[data-baseweb="tab"]:nth-child(7)[aria-selected="true"] p {
            color: white !important;
        }
    </style>
""", unsafe_allow_html=True)




# ----------------------------------------------------------
# ----------------- FUNCIONES DASHBOARD --------------------
# ----------------------------------------------------------
def login():
    # 1. Obtener los datos de los inputs de sesión
    username = st.session_state["input_user"]
    password = st.session_state["input_pass"]

    # 2. Acceder al diccionario de usuarios en secrets
    users = st.secrets["users"]

    # 3. Validar existencia de usuario y coincidencia de contraseña
    if username in users and users[username]["password"] == password:
        st.session_state.logged_in = True
        st.session_state.username = username
        
        # Guardamos el rol (admin/user) para usarlo en el resto de la app
        st.session_state.role = users[username]["role"]
        
        st.session_state.login_error = False
    else:
        # Si falla, nos aseguramos de que no entre
        st.session_state.logged_in = False
        st.session_state.login_error = True


@st.cache_data
def cargar_dataframe_desde_s3(bucket_name):
    # 1. Inicializar clientes
    session = boto3.Session(
            aws_access_key_id=st.secrets['aws_credentials']['aws_access_key_id'],
            aws_secret_access_key=st.secrets['aws_credentials']['aws_secret_access_key'],
            aws_session_token=st.secrets['aws_credentials']['aws_session_token'],
            region_name=st.secrets['aws_credentials']['region_name']
        )
    dynamodb = session.resource('dynamodb')
    s3 = session.client('s3')
    table = dynamodb.Table(st.secrets['aws_credentials']['dynamodb_table_status'])

    try:
        # 2. Obtener ruta del archivo más reciente
        response = table.get_item(Key={'status_id': 'LATEST_STATE'}) 
        
        if 'Item' not in response:
            print("No se encontró el estado LATEST_STATE")
            return None
            
        # 3. Descargar el archivo de S3 directamente a memoria
        s3_key = response['Item']['current_file']
        buffer = io.BytesIO()
        s3.download_fileobj(bucket_name, s3_key, buffer)
        buffer.seek(0)

        # 4. Cargar en DataFrame (asumiendo que es un Parquet)
        df_petrola = pd.read_parquet(buffer)

        # 5. Convertir fechas
        if "sample_date" in df_petrola.columns:
            df_petrola["sample_date"] = pd.to_datetime(df_petrola["sample_date"])

        df_petrola = df_petrola.rename(columns={
            'Component RT': 'component_rt',
            'Library RT': 'library_rt',
            'Compound Name': 'name',
            'Match Factor': 'match_factor',
            'Formula': 'formula',
            'CAS#': 'cas'
        })
        
        return df_petrola

    except ClientError as e:
        print(f"Error de AWS: {e}")
        return None
    except Exception as e:
        print(f"Error inesperado: {e}")
        return None


@st.cache_data
def generar_diccionario_de_colores_de_grupo(df_petrola):
    # Crea un diccionario de colores para cada grupo, de forma que se pueda usar el mismo color para cada grupo en diferentes tablas.
    # Al igual que la anterior, solo se ejecuta una vez cada hora para mejorar rendimiento
    # El diccionario creado tiene el formato {'nombre_grupo' : 'color'}

    grupos = df_petrola['group'].unique().tolist()
    diccionario_grupos_colores = {}
    lista_colores = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173',
    '#5254a3', '#9c9ede', '#17becf', '#9edae5', '#e6550d',
    '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5', '#c49c94',
    '#f7b6d2', '#c7c7c7', '#dbdb8d', '#aec7e8', '#8c564b',
    '#bd9e39', '#e7ba52', '#d6616b', '#e7969c', '#7b4173',
    '#ce6dbd', '#de9ed6', '#6b6ecf', '#9c9ede', '#393b79',
    '#cedb9c', '#8ca252', '#e7cb94', '#bd9e39', '#ad494a',
    '#a55194', '#6b6ecf', '#637939', '#d62728', '#1f77b4'
]

    for i, grupo in enumerate(grupos):
        diccionario_grupos_colores[grupo] = lista_colores[i]

    return diccionario_grupos_colores


@st.cache_data
def generar_diccionario_de_colores_de_estacion(df_petrola):
    # Función idéntica a la anterior, pero asigna colores a las estaciones. Para que el grafico de barras y mapa tengan los mismos colores
    estaciones = df_petrola['station_id'].unique().tolist()
    diccionario_estaciones_colores = {}
    lista_colores = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173',
    '#5254a3', '#9c9ede', '#17becf', '#9edae5', '#e6550d',
    '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5', '#c49c94',
    '#f7b6d2', '#c7c7c7', '#dbdb8d', '#aec7e8', '#8c564b',
    '#bd9e39', '#e7ba52', '#d6616b', '#e7969c', '#7b4173',
    '#ce6dbd', '#de9ed6', '#6b6ecf', '#9c9ede', '#393b79',
    '#cedb9c', '#8ca252', '#e7cb94', '#bd9e39', '#ad494a',
    '#a55194', '#6b6ecf', '#637939', '#d62728', '#1f77b4'
]

    for i, estacion in enumerate(estaciones):
        diccionario_estaciones_colores[estacion] = lista_colores[i]

    return diccionario_estaciones_colores

def plot_evolution_over_time(df_filtrado, orden_periodo, filtros, diccionario_colores):
    # Función que muestra la evolución de detección de muestras según los filtros seleccionados (Compuestos, grupos, estaciones y tiempo)

    # Se obtienen los filtros seleccionados
    compuesto_sel = filtros["compuestos"]
    familia_sel = filtros["familias"]
    estacion_sel = filtros["estaciones"]
    tipo_visualizacion = filtros["modo_estacion"]
    tipo_estacion = filtros["tipo_estacion"]

    # Se crea la figura
    fig = go.Figure()

    # Se agregan por compuestos, grupos o estaciones segun los filtros seleccionados.
    # La lógica se explica a continuación (0 para no seleccionados y 1 para seleccionados):
    #   Compuesto (0) - Grupo (0) -> Se muestran los 8 grupos mas frecuentes
    #   Compuesto (0) - Grupo (1) -> Se muestra la evolución de grupos seleccionados en la gráfica
    #   Compuesto (1) - Grupo (0) -> Se muestra la evolución de compuestos seleccionados en la gráfica
    #   Compuesto (1) - Grupo (1) -> Se muestra la evolución de compuestos seleccionados en la gráfica
    if tipo_visualizacion == "Grupo/Compuesto":
        if compuesto_sel:
            frecuencia = df_filtrado.groupby(['name', 'periodo']).size().unstack(fill_value=0)
            titulo = 'Compuesto'
            leyenda = titulo
            indices = compuesto_sel
        else:
            if not familia_sel or len(familia_sel) == 0:
                top_familias = df_filtrado['group'].value_counts().nlargest(8).index.tolist()
            else:
                top_familias = familia_sel

            df_limite_8_familias = df_filtrado[df_filtrado['group'].isin(top_familias)]
            frecuencia = df_limite_8_familias.groupby(['group', 'periodo']).size().unstack(fill_value=0)
            titulo = 'Grupo'
            leyenda = titulo
            indices = frecuencia.index.tolist()

        frecuencia = frecuencia.reindex(columns=orden_periodo, fill_value=0)

        for item in indices:
            if item in frecuencia.index:
                color = diccionario_colores.get(item, None) if titulo == 'Grupo' else None
                fig.add_trace(go.Scatter(
                    x=frecuencia.columns,
                    y=frecuencia.loc[item],
                    mode='lines+markers',
                    name=str(item),
                    marker=dict(size=8, color=color) if color else dict(size=8)
                ))
    elif tipo_visualizacion == "Estación":
        if compuesto_sel:
            if len(compuesto_sel) > 4:
                return
            
            if len(estacion_sel) > 4:
                return
            if len(estacion_sel) == 0 or estacion_sel == None:
                return
            
            titulo = 'Compuesto'
            leyenda = 'Compuesto - Estación'
            df_individual = df_filtrado[df_filtrado['name'].isin(compuesto_sel)]

            for compuesto in compuesto_sel:
                df_comp = df_individual[df_individual['name'] == compuesto]

                estaciones_unicas = df_comp['station_id'].unique()

                for estacion in estaciones_unicas:
                    df_est = df_comp[df_comp['station_id'] == estacion]
                    frecuencia = df_est.groupby('periodo').size().reindex(orden_periodo, fill_value=0)

                    fig.add_trace(go.Scatter(
                        x=frecuencia.index,
                        y=frecuencia.values,
                        mode='lines+markers',
                        name=f'{compuesto} - {estacion}',
                        marker=dict(size=8)
                    ))
        elif familia_sel:
            if len(familia_sel) > 4:
                return
            if len(estacion_sel) > 4:
                return
            if len(estacion_sel) == 0 or estacion_sel == None:
                return
            
            titulo = 'Grupo'
            leyenda = 'Grupo - Estación'
            df_individual = df_filtrado[df_filtrado['group'].isin(familia_sel)]

            for familia in familia_sel:
                df_comp = df_individual[df_individual['group'] == familia]

                estaciones_unicas = df_comp['station_id'].unique()

                for estacion in estaciones_unicas:
                    df_est = df_comp[df_comp['station_id'] == estacion]
                    frecuencia = df_est.groupby('periodo').size().reindex(orden_periodo, fill_value=0)

                    fig.add_trace(go.Scatter(
                        x=frecuencia.index,
                        y=frecuencia.values,
                        mode='lines+markers',
                        name=f'{familia} - {estacion}',
                        marker=dict(size=8)
                    ))
        else:
            return

    # Creación de un titulo dinamico, dependiendo de si se han seleccionado estaciones, grupos o compuestos.
    if estacion_sel:
        if len(estacion_sel) > 5:
            estaciones_str = ", ".join(str(e) for e in estacion_sel[:5]) + "..."
        else:
            estaciones_str = ", ".join(str(e) for e in estacion_sel)
        title = f'Evolución de detección de {titulo}s - Estación(es) {estaciones_str}'
    else:
        if tipo_estacion:
            tipos = " ,".join(str(tipo) for tipo in tipo_estacion)
            grupos_o_todas = f"Estaciones de tipo: {tipos}"
        else:
            grupos_o_todas = "Todas las Estaciones"

        title = f'Evolución de detección de {titulo}s - {grupos_o_todas}'


    # Se eliminan el nombre de los ejes, para que la gráfica sea más grande y se vea mejor
    fig.update_layout(
        title=title,
        xaxis_title="",
        yaxis_title="",
        xaxis=dict(tickangle=45),
        legend_title_text=leyenda,
        showlegend=True,
        height=620
    )

    # Se dibuja la gráfica en streamlit usando todo el ancho disponible
    st.plotly_chart(fig, use_container_width=True)


def plot_boxplot_match_factor(df_filtrado, familia_sel, diccionario_colores_grupos, valor_barras_horizontales, mostrar_quesito):
    # Función que genera una gráfica de boxplots, dependiendo de si se han elegido grupos o compuestos.
    # Sigue la misma lógica que la función anterior.
    
    # Originalmente se añadió un gráfico de quesito (ahora comentado). Ahora siempre se muestran 18 si no se ha seleccionado ninguno.
    if mostrar_quesito:
        numero_grupos_a_mostrar = 8
    else:
        if len(df_filtrado['group'].unique()) < 18:
            numero_grupos_a_mostrar = len(df_filtrado['group'].unique())
        else:
            numero_grupos_a_mostrar = 18
    
    if not familia_sel:
        top_familias = df_filtrado['group'].value_counts().nlargest(numero_grupos_a_mostrar).index.tolist()
    else:
        top_familias = familia_sel

    # Se filtra el dataframe por los grupos seleccionados
    df_boxplot = df_filtrado[df_filtrado['group'].isin(top_familias)]
    if df_boxplot.empty:
        st.write("No hay datos para mostrar.")
        return

    # Se crea el boxplot con los colores del diccionario de grupos
    fig = px.box(
        df_boxplot,
        x='group',
        y='match_factor',
        color='group',
        title='Distribución de Match Factor por Grupo',
        color_discrete_map=diccionario_colores_grupos,
        height=600
    )

    # Se elimina el nombre de los ejes para hacer la figura más grande
    fig.update_layout(showlegend=False, xaxis_title='', yaxis_title='')
    fig.update_yaxes(range=[70,100])

    # Se añaden dos lineas horizontales que muestran el rango de match factor seleccionado.
    fig.add_hline(y=valor_barras_horizontales[0], line_dash="dash", line_color="red")
    fig.add_hline(y=valor_barras_horizontales[1], line_dash="dash", line_color="red")

    # Se dibuja el gráfico en streamlit, usando todo el ancho disponible.
    st.plotly_chart(fig, use_container_width=True)


def plot_top_grupos(df_filtrado, diccionario_colores):
    # Gráfica de quesito mostrado originalmente.

    # Se calculan las frecuencias de cada grupo
    grupos_freq = df_filtrado["group"].value_counts()
        
    # Si existen más de 8 grupos diferentes, se muestran los 8 más frecuentes y se agrupan el resto en 'Otros'. Por temas de espacio en la visualización.
    if len(grupos_freq) > 8:
        top8 = grupos_freq[:8]
        otros = grupos_freq[8:].sum()
        top8["Otros"] = otros
    else:
        top8 = grupos_freq

    # Se calculan los compuestos más frecuentes de cada grupo.
    top_compuestos = (
        df_filtrado.groupby(["group", "name"])
        .size()
        .reset_index(name='frecuencia')
        .sort_values(['group', 'frecuencia'], ascending=[True, False])
    )

    # Se seleccionan los 3 más frecuentes de cada grupo, para la información del hover.
    top3_por_grupo = (
        top_compuestos
        .groupby("group")
        .head(3)
        .groupby("group")["name"]
        .apply(lambda x: " | ".join(x))
    )

    # Se crea el dataframe con los grupos que se van a mostrar, su frecuencia y los 3 compuestos más frecuentes de cada grupo.
    df_top8 = top8.reset_index()
    df_top8.columns = ['Grupo', 'Frecuencia']
    df_top8["Top compuestos"] = df_top8["Grupo"].map(top3_por_grupo)
    df_top8["Top compuestos"] = df_top8["Top compuestos"].fillna("No disponible")

    # Se crear el gráfico de quesito con los colores del diccionario
    fig = px.pie(
        df_top8,
        names='Grupo',
        values='Frecuencia',
        hover_data=['Top compuestos'],
        color='Grupo',
        color_discrete_map=diccionario_colores
    )
    
    # Se añade la información que se mostrará al hacer hover sobre cada porción. Nombre, NºMuestras y compuestos más frecuentes.
    fig.update_traces(
        textinfo='percent+label',
        hovertemplate="<b>%{label}</b><br>Nº muestras: %{value}<br>Top compuestos: %{customdata[0]}<extra></extra>"
    )
    
    # Se ajustan los margenes y proporciones para el espacio disponible y se muestra
    fig.update_layout(showlegend=False, height= 570, width= 570, title="Proporción de Grupos según detecciones",margin=dict(t=65, b=50, l=0, r=0),)
    st.plotly_chart(fig, use_container_width=True)

@st.cache_data
def load_geodata():
    """
    Descarga el conjunto de archivos del Shapefile de S3 a /tmp y los carga en un GeoDataFrame.
    """
    bucket_name = st.secrets['aws_credentials']['bucket_name']
    prefix = "medallion/referencies/geo_data/limite_hidrogeologico"
    
    # Extensiones necesarias para que el Shapefile sea válido
    extensions = ['.shp', '.shx', '.dbf', '.prj', '.cpg', '.qpj']
    
    # 1. Inicializar el cliente de S3
    s3 = boto3.client(
        's3',
        aws_access_key_id=st.secrets['aws_credentials']['aws_access_key_id'],
        aws_secret_access_key=st.secrets['aws_credentials']['aws_secret_access_key'],
        aws_session_token=st.secrets['aws_credentials'].get('aws_session_token'), # .get por si no existe
        region_name=st.secrets['aws_credentials']['region_name']
    )

    local_path_base = "/tmp/limite_hidrogeologico"

    try:
        # 2. Descargar cada uno de los archivos auxiliares
        for ext in extensions:
            s3_key = f"{prefix}{ext}"
            local_file = f"{local_path_base}{ext}"
            
            # Descargamos el archivo de S3 al almacenamiento temporal del servidor
            s3.download_file(bucket_name, s3_key, local_file)
        
        # 3. Leer el archivo .shp localmente con geopandas
        gdf = gpd.read_file(f"{local_path_base}.shp")

        return gdf

    except Exception as e:
        st.error(f"Error al cargar datos geográficos desde S3: {e}")
        return None


def plot_station_map_plotly(df_filtrado, estaciones_color):
    # Función que crea un mapa de la laguna con los limites hidrológicos y marca las estaciones como puntos en el mapa.

    # Se leen los límites desde s3 y se convierten a WGS84
    bounds = load_geodata()
    bounds_wsg84 = bounds.to_crs('EPSG:4326')
    bounds_geojson = bounds_wsg84.__geo_interface__

   
    # Se procesan las coordeandas de las estaciones para generar los marcadores
    estaciones = (
        df_filtrado[['station_id', 'x', 'y', 'st_type', 'geology']]
        .dropna(subset=['x', 'y'])
        .drop_duplicates(subset=['station_id'])
        .set_index('station_id')[['x', 'y', 'st_type', 'geology']]
    )

    # Se crea un geopandas dataframe con las estaciones y se pasa al sistema necesario para mostrar en la gráfica.
    geo_pts = gpd.points_from_xy(estaciones['x'], estaciones['y'], crs='EPSG:25830')
    stations_gdf = gpd.GeoDataFrame(estaciones, geometry=geo_pts)
    stations_wsg84 = stations_gdf.to_crs('EPSG:4326')


    # Se calcula el número de muestras por estación, para la información de hover
    num_muestras = df_filtrado.groupby('station_id').size().rename('muestras')
    stations_wsg84 = stations_wsg84.join(num_muestras, on='station_id')


    # Se crea el dataframe con cada estación, los compuestos y su numero de detecciones.
    compuestos_por_estacion = (
        df_filtrado.groupby(['station_id', 'name'])
        .size()
        .reset_index(name='cuenta')
    )

    # Se itera por cada estación, creando la inforamción de hover (ID, NºMuestras, Geologia y Compuestos) y añadiendola al diccionario.
    hover_data = {}
    for station_id, grp in compuestos_por_estacion.groupby('station_id'):
        grp_sorted = grp.sort_values('cuenta', ascending=False)
        top5 = grp_sorted.head(5)
        otros = grp_sorted['cuenta'].iloc[5:].sum()
        lines = [f"{row['name']}: {row['cuenta']}" for _, row in top5.iterrows()]
        if otros > 0:
            lines.append(f"Otros: {otros}")
        geol = stations_wsg84.loc[station_id, 'geology']
        total = stations_wsg84.loc[station_id, 'muestras']
        texto = (
            f"<b>Estación:</b> {station_id}<br>"
            f"<b>Muestras totales:</b> {total}<br>"
            f"<b>Geología:</b> {geol}<br>"
            f"<b>Compuestos:</b><br>" + "<br>".join(lines)
        )
        hover_data[station_id] = texto

    # Variables para mostrar las estaciones en el gráfico Plotly
    lats = stations_wsg84.geometry.y.tolist()
    lons = stations_wsg84.geometry.x.tolist()
    station_ids = stations_wsg84.index.tolist()
    hover_texts = [hover_data[st] for st in station_ids]

    # Se crea la figura
    fig = go.Figure()

    # Se añade la linea de limite de la laguna
    for feature in bounds_geojson['features']:
        coords = feature['geometry']['coordinates'][0]
        lon_coords = [pt[0] for pt in coords]
        lat_coords = [pt[1] for pt in coords]
        fig.add_trace(go.Scattermap(
            lon=lon_coords,
            lat=lat_coords,
            mode='lines',
            line=dict(width=2, color='blue'),
            fill='toself',
            fillcolor='rgba(0,0,255,0.1)',
            hoverinfo='none',
            showlegend=False
        ))

    # Se denfinen los colores para cada marcador (estación) segun el diccionario de colores y se dibujan en el mapa
    colores = [estaciones_color.get(est, '#cccccc') for est in station_ids]
    fig.add_trace(go.Scattermap(
        lon=lons,
        lat=lats,
        mode='markers',
        marker=go.scattermap.Marker(
            size=16,
            color=colores, 
            opacity=1
        ),
        text=hover_texts,
        hoverinfo='text',
        showlegend=False
    ))

    # Se personalizan los valores iniciales del mapa y su tamaño    
    fig.update_layout(
        map=dict(
            style='satellite',
            center=dict(lat=38.84, lon=-1.5609350),
            zoom=13
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=585
    )

    # Se dibuja la gráfica en Streamlit
    st.plotly_chart(fig, use_container_width=True)

def obtener_estacion(fecha):
    # Esta función toma una fecha y devuelve la estación del año en la que se encuentra dicha fecha.
    mes = fecha.month
    if mes in [12, 1, 2]:
        return 'Invierno'
    elif mes in [3, 4, 5]:
        return 'Primavera'
    elif mes in [6, 7, 8]:
        return 'Verano'
    else:
        return 'Otoño'
def aplicar_filtros(df, filtros):
    # Función que toma el Dataframe original (sin filtrar) y aplica los filtros que se hayan seleccionado

    # En primer lugar se crea una copia del dataframe original, no queremos modificarlo.
    df_filtrado = df.copy()

    # filtros es un diccionario que contiene todos los filtros y su valor.
    # El proceso de filtrado consiste en verificar si el filtro tiene un valor seleccionado y filtrar por dicho valor.
    if filtros["compuestos"]:
        df_filtrado = df_filtrado[df_filtrado["name"].isin(filtros["compuestos"])]

    if filtros["familias"]:
        df_filtrado = df_filtrado[df_filtrado["group"].isin(filtros["familias"])]

    # De momento el rango de match factor no filtra el dataframe, solo mueve las lineas horizontales de la gráfica.
    # Se puede descomentar este codigo para añadir la funcionalidad de filtrar el dataframe por match_factor
    #df_filtrado = df_filtrado[
    #    (df_filtrado["match_factor"] >= match_factor_sel[0]) &
    #    (df_filtrado["match_factor"] <= match_factor_sel[1])
    #    ]

    if filtros["estaciones"]:
        df_filtrado = df_filtrado[df_filtrado["station_id"].isin(filtros["estaciones"])]

    if filtros["tipo_estacion"]:
        df_filtrado = df_filtrado[df_filtrado["st_type"].isin(filtros["tipo_estacion"])]

    if filtros["tipo_tiempo"] == "Intervalo":
        inicio, fin = filtros["rango_fechas"]
        df_filtrado = df_filtrado[
            (df_filtrado["sample_date"] >= pd.to_datetime(inicio)) &
            (df_filtrado["sample_date"] <= pd.to_datetime(fin))
        ]

    # Periodo para gráficos
    if filtros["tipo_tiempo"] == "Mensual":
        df_filtrado["periodo"] = df_filtrado["sample_date"].dt.strftime('%b')
        orden = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    elif filtros["tipo_tiempo"] == "Estacional":
        df_filtrado["periodo"] = df_filtrado["sample_date"].apply(obtener_estacion)
        orden = ['Primavera', 'Verano', 'Otoño', 'Invierno']
    else:
        df_filtrado["periodo"] = df_filtrado["sample_date"].dt.to_period("M").dt.to_timestamp()
        orden = sorted(df_filtrado['periodo'].unique())

    return df_filtrado, orden



def insertar_nuevas_muestras(uploaded_files, descripcion="Carga desde Dashboard"):
    """
    Sube archivos a S3 con una interfaz minimalista y dispara la Lambda mediante un JSON.
    """
    total_files = len(uploaded_files)
    status_placeholder = st.empty() 
    progress_bar = st.progress(0)
    
    # 1. Configuración de Identificadores y Cliente
    execution_id = f"exec-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"
    bucket_name = st.secrets['aws_credentials']['bucket_name']
    user = st.session_state.get("username")
    
    s3 = boto3.client(
        's3',
        aws_access_key_id=st.secrets['aws_credentials']['aws_access_key_id'],
        aws_secret_access_key=st.secrets['aws_credentials']['aws_secret_access_key'],
        aws_session_token=st.secrets['aws_credentials'].get('aws_session_token'),
        region_name=st.secrets['aws_credentials']['region_name']
    )

    uploaded_keys = []

    try:
        # 2. Bucle de subida real de archivos Excel
        for i, file in enumerate(uploaded_files, 1):
            status_placeholder.info(f"📤 **Subiendo archivo {i}/{total_files}:** `{file.name}`")
            
            # Generamos la ruta en S3
            file_key = f"landing/{execution_id}/{file.name}"
            
            # Subida del archivo (usamos getvalue() porque Streamlit lo tiene en memoria)
            s3.put_object(
                Bucket=bucket_name,
                Key=file_key,
                Body=file.getvalue()
            )
            
            uploaded_keys.append(file_key)
            progress_bar.progress(i / total_files)

        # 3. Creación y subida del JSON "Trigger"
        status_placeholder.warning("**Finalizando: Generando señal de proceso...**")
        
        ready_to_ingest = {
            "execution_id": execution_id,
            "user": user,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "number_of_excel_files": total_files,
            "description": descripcion,
            "is_rollback": False,
            "ids_to_revoke": [],
            "files_paths": uploaded_keys
        }

        # Subimos el JSON al mismo prefijo (esto es lo que activa tu Lambda)
        json_key = f"landing/{execution_id}/ready_to_ingest.json"
        s3.put_object(
            Bucket=bucket_name,
            Key=json_key,
            Body=json.dumps(ready_to_ingest, indent=4)
        )

        # 4. Limpieza de Interfaz
        status_placeholder.empty()
        progress_bar.empty()
        
        return True, execution_id

    except Exception as e:
        status_placeholder.error(f"Error en la subida: {str(e)}")
        progress_bar.empty()
        return False, None



@st.cache_data
def load_image_excel():
    """
    Recupera los bytes de una imagen desde S3 para mostrarla en Streamlit.
    """
    bucket_name = st.secrets['aws_credentials']['bucket_name']
    prefix = "medallion/referencies/images/Estructura_excel_referencia_para_insertado_de_nuevos_datos.JPG"

    # 1. Inicializar cliente
    s3 = boto3.client(
        's3',
        aws_access_key_id=st.secrets['aws_credentials']['aws_access_key_id'],
        aws_secret_access_key=st.secrets['aws_credentials']['aws_secret_access_key'],
        aws_session_token=st.secrets['aws_credentials'].get('aws_session_token'),
        region_name=st.secrets['aws_credentials']['region_name']
    )

    try:
        # 2. Obtener el objeto de S3
        response = s3.get_object(Bucket=bucket_name, Key=prefix)
        
        # 3. Leer los bytes del cuerpo de la respuesta
        image_bytes = response['Body'].read()
        
        return image_bytes

    except Exception as e:
        st.error(f"Error al cargar la imagen desde S3: {e}")
        return None


def fetch():
    try:
        dynamodb = boto3.resource(
            'dynamodb',
            aws_access_key_id=st.secrets['aws_credentials']['aws_access_key_id'],
            aws_secret_access_key=st.secrets['aws_credentials']['aws_secret_access_key'],
            aws_session_token=st.secrets['aws_credentials']['aws_session_token'],
            region_name=st.secrets['aws_credentials']['region_name']
        )
        table = dynamodb.Table(st.secrets['aws_credentials']['dynamodb_table_status'])
        
        # Buscamos la fila única con tu PK específica
        response = table.get_item(Key={'status_id': 'LATEST_STATE'})
        return response.get('Item')
    except Exception as e:
        st.error(f"Error al consultar DynamoDB: {e}")
        return None


# Cache de 5 minutos para comprobaciones rutinarias
@st.cache_data(ttl=300)
def fetch_cached():
    return fetch()


def obtener_metadata_actual_dynamo(use_cache=True):
    """Consulta la única fila de DynamoDB para obtener el estado del Datalake."""
    if use_cache:
        return fetch_cached()
    else:
        # Sin cache para cuando estamos esperando a la Lambda
        return fetch()



def monitorizar_actualizacion_lambda(nuevo_id_esperado, timeout_seg=300, is_revoke=False):
    """Bloquea y monitoriza hasta que DynamoDB se actualice o pase el tiempo límite."""
    start_time = time.time()
    
    if is_revoke:
        mensaje_status = "🗑️ Revocando insercciones..."
    else:
        mensaje_status = "🛠️ Procesando muestras en..."
    
    with st.status(mensaje_status, expanded=True) as status:
        st.write("Se están procesando las muestras. Esto puede tardar unos minutos...")
        placeholder_info = st.empty()

        while (time.time() - start_time) < timeout_seg:
            # Consulta a DynamoDB solo una vez por ciclo
            meta = obtener_metadata_actual_dynamo(use_cache=False)

            if meta and meta.get("last_execution_id") == nuevo_id_esperado:
                status.update(label="Datos procesados con éxito", state="complete", expanded=False)
                st.cache_data.clear()
                st.session_state["id_referencia"] = nuevo_id_esperado
                time.sleep(2)
                st.session_state["uploader_key"] += 1
                st.rerun()
                return

            # Cuenta 1 a 1 durante 20s sin volver a consultar DynamoDB
            for _ in range(20):
                if (time.time() - start_time) >= timeout_seg:
                    break
                elapsed = int(time.time() - start_time)
                placeholder_info.caption(f"⏳ Tiempo en espera: {elapsed}s / {timeout_seg}s")
                time.sleep(1)

        status.update(label="El proceso ha tardado demasiado", state="error")
        st.error("La base de datos no se ha actualizado en 10 min. Revisa AWS.")




@st.cache_data
def obtener_historial_updatelog():
    """
    Obtiene solo las columnas necesarias y filtra por éxito y tipo de operación
    directamente en AWS antes de descargar los datos.
    """
    try:
        creds = st.secrets["aws_credentials"]
        dynamodb = boto3.resource(
            'dynamodb',
            aws_access_key_id=creds['aws_access_key_id'],
            aws_secret_access_key=creds['aws_secret_access_key'],
            aws_session_token=creds.get('aws_session_token'),
            region_name=creds['region_name']
        )
        table = dynamodb.Table("UpdateLog")

        # Realizamos el escaneo con filtros y proyección de columnas
        response = table.scan(
            # 1. Filtros
            FilterExpression=Attr('operation_type').eq('SAMPLE_INGESTION') & 
                            Attr('operation_status').eq('SUCCESS'),
            
            # 2. ProjectionExpression: Usamos alias para 'timestamp' (#ts) y 'user' (#usr)
            ProjectionExpression="#ts, execution_id, records_affected, #usr, excel_files, number_of_files",
            
            # 3. Mapeo de alias
            ExpressionAttributeNames={
                "#ts": "timestamp", 
                "#usr": "user"
            }
        )
        
        items = response.get('Items', [])
        df = pd.DataFrame(items)
        
        if not df.empty:
            # 1. Convertir la columna 'timestamp' a objeto datetime real
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # 2. Ajustar al horario de España
            df['timestamp'] = df['timestamp'].dt.tz_convert('Europe/Madrid')

            # 3. Ordenar por fecha antes de pasar a texto
            df = df.sort_values(by='timestamp', ascending=False)

            # 4. Formatear la fecha a String legible para la tabla
            df['timestamp'] = df['timestamp'].dt.strftime('%d/%m/%Y - %H:%M')
            
            # 4. Reordenar columnas
            df = df[['execution_id', 'timestamp', 'records_affected', 'number_of_files', 'excel_files', 'user']]
            
        return df

    except Exception as e:
        st.error(f"❌ Error al consultar UpdateLog: {e}")
        return pd.DataFrame()
    

def eliminar_insercion_aws(ids_a_revocar, execution_id):
    
    bucket_name = st.secrets['aws_credentials']['bucket_name']
    user = st.session_state.get("username")
    try: 
        s3 = boto3.client(
            's3',
            aws_access_key_id=st.secrets['aws_credentials']['aws_access_key_id'],
            aws_secret_access_key=st.secrets['aws_credentials']['aws_secret_access_key'],
            aws_session_token=st.secrets['aws_credentials'].get('aws_session_token'),
            region_name=st.secrets['aws_credentials']['region_name']
        )
        
        print("Conexion")
        ready_to_ingest = {
                "execution_id": execution_id,
                "user": user,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "number_of_excel_files": 0,
                "description": f"Revocación de la insercción/es con id {ids_a_revocar}",
                "is_rollback": True,
                "ids_to_revoke": ids_a_revocar
            }
        print(f"Json: {ready_to_ingest}")
        # Subimos el JSON al mismo prefijo (esto es lo que activa tu Lambda)
        
        json_key = f"landing/{execution_id}/ready_to_ingest.json"
        s3.put_object(
            Bucket=bucket_name,
            Key=json_key,
            Body=json.dumps(ready_to_ingest, indent=4)
        )

        print("Subido")
        return True

    except Exception as e:
        return False





def _get_dynamodb_resource():
    creds = st.secrets["aws_credentials"]
    return boto3.resource(
        'dynamodb',
        aws_access_key_id=creds['aws_access_key_id'],
        aws_secret_access_key=creds['aws_secret_access_key'],
        aws_session_token=creds.get('aws_session_token'),
        region_name=creds['region_name']
    )
 
 
@st.cache_data
def obtener_updatelog():
    """Obtiene todos los registros de UpdateLog y los devuelve como DataFrame."""
    try:
        table = _get_dynamodb_resource().Table("UpdateLog")
        response = table.scan(
            ProjectionExpression=(
                "#ts, execution_id, operation_type, operation_status, details, "
                "#usr, records_affected, number_of_files, excel_files, "
                "duration_ms, target_entity, total_samples_after_operation"
            ),
            ExpressionAttributeNames={"#ts": "timestamp", "#usr": "user"}
        )
        items = response.get('Items', [])
        df = pd.DataFrame(items)
 
        if not df.empty:
            df['timestamp'] = (
                pd.to_datetime(df['timestamp'])
                .dt.tz_convert('Europe/Madrid')
            )
            df = df.sort_values('timestamp', ascending=False)
            df['timestamp'] = df['timestamp'].dt.strftime('%d/%m/%Y - %H:%M')
            df = df[[
                'execution_id', 'timestamp', 'operation_type',
                'operation_status', 'user', 'records_affected',
                'number_of_files', 'excel_files',
                'duration_ms', 'target_entity',
                'total_samples_after_operation'
            ]]
        return df
 
    except Exception as e:
        st.error(f"❌ Error al consultar UpdateLog: {e}")
        return pd.DataFrame()
 
 
@st.cache_data
def obtener_discardedlog():
    """Obtiene todos los registros de DiscardedLog y los devuelve como DataFrame."""
    try:
        table = _get_dynamodb_resource().Table("DiscardedLog")
        response = table.scan(
            ProjectionExpression=(
                "#ts, execution_id, #typ, cause, #act, #fi, #sh, #rw"
            ),
            ExpressionAttributeNames={
                "#ts":  "timestamp",
                "#typ": "type",
                "#act": "action",
                "#fi":  "file",
                "#sh":  "sheet",
                "#rw":  "row"
            }
        )
        items = response.get('Items', [])
        df = pd.DataFrame(items)
 
        if not df.empty:
            df['timestamp'] = (
                pd.to_datetime(df['timestamp'])
                .dt.tz_convert('Europe/Madrid')
            )
            df = df.sort_values('timestamp', ascending=False)
            df['timestamp'] = df['timestamp'].dt.strftime('%d/%m/%Y - %H:%M')
            df = df[['execution_id', 'timestamp', 'type', 'cause', 'action',
                      'file', 'sheet', 'row']]
        return df
 
    except Exception as e:
        st.error(f"❌ Error al consultar DiscardedLog: {e}")
        return pd.DataFrame()
 
 
@st.cache_data
def obtener_currentstatus():
    """Obtiene el registro único de CurrentStatus y lo devuelve como DataFrame."""
    try:
        table = _get_dynamodb_resource().Table("CurrentStatus")
        response = table.scan(
            ProjectionExpression=(
                "status_id, current_file, last_execution_id, "
                "processing_status, updated_at"
            )
        )
        items = response.get('Items', [])
        df = pd.DataFrame(items)
 
        if not df.empty:
            df = df[['status_id', 'current_file', 'last_execution_id',
                      'processing_status', 'updated_at']]
        return df
 
    except Exception as e:
        st.error(f"❌ Error al consultar CurrentStatus: {e}")
        return pd.DataFrame()


TABLE_CONFIG = {
    "Registro de Actualizaciones": {
        "fn": obtener_updatelog,
        "description": "Registro completo de todas las operaciones de inserción, "
                       "actualización y rollback realizadas sobre el sistema.",
    },
    "Registro de Datos Descartados": {
        "fn": obtener_discardedlog,
        "description": "Elementos descartados durante los procesos de inserción: "
                       "archivos, hojas o filas que no superaron la validación.",
    },
    "Estado Actual": {
        "fn": obtener_currentstatus,
        "description": "Estado actual del sistema: archivo maestro vigente y "
                       "estado del procesamiento en tiempo real.",
    },
}





#------------------------------------------------------------
#------------------- AUTENTIFICACIÓN DE USUARIO--------------
#------------------------------------------------------------


# Estado de Sesion
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "login_error" not in st.session_state:
    st.session_state.login_error = False


# Interfaz de login
if not st.session_state.logged_in:
    st.markdown("""
        <h1 style='text-align: center; 
                font-family: "Segoe UI", "Helvetica Neue", sans-serif; 
                font-size: 2.2em; 
                margin-bottom: 0.2em;'>
            Herramienta de Análisis de Muestras<br>Laguna de Pétrola
        </h1>
    """, unsafe_allow_html=True)
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("Usuario", key="input_user")
        st.text_input("Contraseña", type="password", key="input_pass")
        st.button("Acceder", use_container_width=True, on_click=login)
        df_petrola = cargar_dataframe_desde_s3(bucket_name=st.secrets['aws_credentials']['bucket_name'])

        if st.session_state.login_error:
            st.error("Usuario o contraseña incorrectos.")
    
    st.stop()


if "confirmando_eliminacion" not in st.session_state:
    st.session_state.confirmando_eliminacion = False


# --------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------
# ------------------------------------------------ CONTENIDO DASHBOARD -----------------------------------------------
# --------------------------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------------------------


st.subheader("Análisis de muestras de agua – Laguna de Pétrola")
st.markdown("""
    <style>
    .block-container {
        padding-top: 1.6rem;
    }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZACIÓN DE ESTADO ---
if "id_referencia" not in st.session_state:
    meta_inicial = obtener_metadata_actual_dynamo(use_cache=True)
    if meta_inicial:
        st.session_state["id_referencia"] = meta_inicial.get("last_execution_id")


# --- COMPROBACIÓN PASIVA (NOTIFICACIÓN) ---
meta_actual = obtener_metadata_actual_dynamo(use_cache=True)
if meta_actual and meta_actual.get("last_execution_id") != st.session_state["id_referencia"]:
    col1, col2 = st.columns([4, 1], vertical_alignment="center")
    with col1:
        st.info("AVISO: Nuevos datos disponibles. Pulse el boton para actualizarlos")

    with col2:
        if st.button("Actualizar ahora", use_container_width=True):
            st.cache_data.clear()
            st.session_state["id_referencia"] = meta_actual.get("last_execution_id")
            st.rerun()


# Key para saber si hay que limpiar la lista de archivos subidos
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = 0


# Se carga el dataframe, extrayendo los datos de la base de datos
df_petrola = cargar_dataframe_desde_s3(
    bucket_name=st.secrets['aws_credentials']['bucket_name']
)

# Verificamos que le dataframe se cargó correctamente desde S3
if df_petrola is None or df_petrola.empty:
    # 1. Limpiamos el caché para forzar una lectura limpia en el próximo intento
    st.cache_data.clear()
    
    # 2. Mostramos el mensaje de error al usuario
    st.error("⚠️ Error de conexión con el almacenamiento (S3) o los datos están vacíos.")
    st.info("Por favor, vuelve a intentarlo más tarde o contacta con el administrador si el problema persiste.")
    if st.button("🔄 Reintentar conexión"):
        st.rerun()
    st.stop()

# Se inicializa el diccionario de filtros
filtros = {}

# Se generan los colores de los grupos
grupos_color = generar_diccionario_de_colores_de_grupo(df_petrola)

# Se generan los colores de las estaciones
estaciones_color = generar_diccionario_de_colores_de_estacion(df_petrola)

# Espacio reservado para situar las métricas en la parte superior del dashboard
metrics_placeholder = st.empty()

# Reserva un espacio fijo para que cuando se recargue el dataframe, no suban todos los elementos y vuelvan a bajar de rápidamente
metrics_placeholder.markdown(
    "<div style='height:115px'></div>", 
    unsafe_allow_html=True
)
st.text("")

# Parte inferior (Filtros)
with st.container():
    st.markdown("<hr style='border:1px solid #ccc; margin-top:2px; margin-bottom:2px;' />", unsafe_allow_html=True)
    
    # Si es admin, puede ver las secciones de añadir_datos y eliminar insercciones
    if st.session_state.get("role") == "admin":
        compuestos_tab, stations_tab, time_tab, filtered_data_tab, add_data_tab, delete_insertions_tab, audit_tab = st.tabs(["🧪 Compuestos y Grupos", "📡 Estaciones", "📈 Evolución Temporal","📄 Datos Filtrados", "➕ Añadir nuevos datos", "🚫 Eliminar insercciones", "🗂️ Auditoría"])
    else:
        compuestos_tab, stations_tab, time_tab, filtered_data_tab = st.tabs(["🧪 Compuestos y Grupos", "📡 Estaciones", "📈 Evolución Temporal","📄 Datos Filtrados"])
    
    with compuestos_tab:

        # ---------------------------------------------------------------------
        # ----------------PESTAÑA 1: Compuestos y Grupos (Filtros) ------------
        # ---------------------------------------------------------------------

        filtros_match_bar, resto = st.columns([1.5, 4.65])

        with filtros_match_bar:
            filtros_match_bar.text("")
            filtros_match_bar.text("")


            st.markdown("""<div style='font-weight: 900; display: block; margin: 0; padding: 0;'>Selección de Compuestos</div>""",unsafe_allow_html=True)
            
            
            # Familias / Grupos
            familias = sorted(df_petrola["group"].dropna().unique())
            familia_sel = st.multiselect(
                "Grupo(s)", 
                familias, 
                default=None,
                placeholder="Todos"
            )
            filtros['familias'] = familia_sel if familia_sel else []
            

            # Compuestos
            if familia_sel:
                df_compuestos_por_grupo = df_petrola[df_petrola['group'].isin(familia_sel)]
                nombre_grupos = ", ".join(familia_sel)
                nombre_grupos = "Pertenecientes a: "+nombre_grupos
            else:
                df_compuestos_por_grupo = df_petrola
                nombre_grupos = 'Todos'

            compuestos = sorted({f"{name} [{cas}]" for name, cas in zip(df_compuestos_por_grupo['name'], df_compuestos_por_grupo['cas'])})
            compuesto_sel = st.multiselect("Compuesto(s)", compuestos, default=None, placeholder=nombre_grupos, help="Selecciona uno o varios compuestos por nombre o CAS. Si se ha seleccionado un grupo, solo serán seleccionables los compuestos pertenecientes a ese grupo.")
            nombre_compuesto_sel = [compuesto.split(' [')[0] for compuesto in compuesto_sel]
            filtros['compuestos'] = nombre_compuesto_sel

            filtros_match_bar.text("")
            filtros_match_bar.text("")

            st.markdown("<span style='font-weight: 900;'>Rango de Match Factor</span>", unsafe_allow_html=True)
            min_mf = float(df_petrola["match_factor"].min())
            max_mf = float(100)#df_petrola["match_factor"].max())
            match_factor_sel = st.slider(
                "Selecciona rango Match Factor",
                min_value=min_mf,
                max_value=max_mf,
                value=(min_mf, max_mf),
                step=0.1
            )
            filtros['match_factor'] = (min_mf, max_mf)
            
            filtros_match_bar.text("")
            filtros_match_bar.text("")
            # mostrar_quesito = st.checkbox("Mostrar Gráfica de Proporciones", value=False)
        
        with resto:
            #if mostrar_quesito:
            #    vacio_match_bar, grafica_match_bar, grafica_quesito = st.columns([0.15, 2.5,2])
            #else:
            #    vacio_match_bar, grafica_match_bar, grafica_quesito = st.columns([0.15,3,0.000000001])
            vacio_match_bar, grafica_match_bar, grafica_quesito = st.columns([0.15,3,0.000000001])


        with vacio_match_bar:
            pass
    
    with stations_tab:

        # ---------------------------------------------------------------------
        # -------------------PESTAÑA 2: Estaciones (Filtros) ------------------
        # ---------------------------------------------------------------------

        filtros_stations_tab, vacio_stations_tab, grafica_stations_tab = st.columns([1,0.1, 2])
        with filtros_stations_tab:
            filtros_stations_tab.text("")
            st.markdown("<span style='font-weight: 900;'>Selección de estación</span>", unsafe_allow_html=True)

             # Tipo de estación
            tipos_estacion = sorted(df_petrola["st_type"].dropna().unique())
            tipo_estacion_sel = st.multiselect("Tipos de estación", tipos_estacion, default=None, placeholder='Todos')
            filtros['tipo_estacion'] = tipo_estacion_sel


            # Estaciones
            estaciones = sorted(df_petrola["station_id"].dropna().unique())
            # Diccionario id -> etiqueta legible
            etiquetas_estacion = {
                sid: f"{sid} - {df_petrola.loc[df_petrola['station_id'] == sid, 'st_type'].iloc[0]}"
                for sid in estaciones
            }
            estacion_sel_labels = st.multiselect(
                "Estación(es)",
                options=list(etiquetas_estacion.values()),
                default=None,
                placeholder='Todos'
            )

            # Revertir a IDs para filtrar
            label_to_id = {v: k for k, v in etiquetas_estacion.items()}
            estacion_sel = [label_to_id[label] for label in estacion_sel_labels]
            filtros['estaciones'] = [label_to_id[label] for label in estacion_sel_labels]

           

        with vacio_stations_tab:
            pass


    with time_tab:
        # ---------------------------------------------------------------------
        # -----------PESTAÑA 3: Evolición Temporal (Filtros) ------------------
        # ---------------------------------------------------------------------

        filtros_time_bar, vacio_time_bar, grafica_time_bar = st.columns([1,0.1, 3])
        with filtros_time_bar:
            filtros_time_bar.text("")
            filtros_time_bar.text("")
            st.markdown("<span style='font-weight: 900;'>Selección de Tiempo</span>", unsafe_allow_html=True)

            # Tipo de filtro temporal, si se elige Intervaloo, aparece la opción de elegir rango de fechas
            tipo_tiempo = st.selectbox("Filtrar por periodo de tiempo:", ["Mensual", "Estacional", "Intervalo"])
            filtros['tipo_tiempo'] = tipo_tiempo


            # La fecha de elección estará entre la muestra mas antigua y mas reciente detectada
            min_fecha = df_petrola["sample_date"].min()
            max_fecha = df_petrola["sample_date"].max()

            if tipo_tiempo == "Intervalo":
                rango_fechas_sel = st.date_input(
                    "Selecciona rango de fechas",
                    value=(min_fecha, max_fecha),
                    min_value=min_fecha,
                    max_value=max_fecha
                )
                filtros['rango_fechas'] = rango_fechas_sel if len(rango_fechas_sel) == 2 else (min_fecha, max_fecha)
            else:
                filtros['rango_fechas'] = (min_fecha, max_fecha)

            # Agregar por Grupo/Compuesto o Estación
            filtros_time_bar.text("")
            filtros_time_bar.text("")
            #st.markdown("<span style='font-weight: 900;'></span>", unsafe_allow_html=True)
            modo_estacion = st.selectbox(
                "Agregar por:",
                ["Grupo/Compuesto", "Estación"],
                help="En ambos casos se muestra el **conteo de detecciones** por período."
            )
            filtros['modo_estacion'] = modo_estacion

            if modo_estacion == "Estación" and (len(nombre_compuesto_sel) > 4 or len(familia_sel) > 4 or len(estacion_sel) > 4):
                st.warning(
                    "⚠️ Atención: El modo Estación solo permite seleccionar un máximo de 4 compuestos o grupos y 4 estaciones.")
                
            if modo_estacion == "Estación" and ( (len(compuesto_sel) < 1 and len(familia_sel)<1)   or len(estacion_sel) < 1) :
                st.warning(
                    "⚠️ Atención: Debes seleccionar al menos 1 compuesto o grupo y 1 estación para visualizar la gráfica en modo Agregado por Estación.")

        with vacio_time_bar:
            st.markdown("")



    if st.session_state.get("role") == "admin":
        with add_data_tab:
            # ---------------------------------------------------------------------
            # ------------------ PESTAÑA 5: Añadir nuevos datos -------------------
            # ---------------------------------------------------------------------

            informacion, vacio_add, dataframe_muestra_inserccion = st.columns([1,0.1, 1.5])
            with dataframe_muestra_inserccion:
                dataframe_muestra_inserccion.text("")
                st.markdown("<span style='font-weight: 900;'>Archivo con estructura válida para la inserción</span>", unsafe_allow_html=True)
                st.image(load_image_excel())

            with informacion:
                #st.subheader("Importar Datos")
                informacion.text("")
                st.markdown("<span style='font-weight: 900;'>Importar nuevos datos</span>", unsafe_allow_html=True)

                uploaded_files = st.file_uploader(
                    "Subir uno o varios archivos Excel",
                    type=["xls", "xlsx"],
                    accept_multiple_files=True,
                    key=f"uploader_{st.session_state['uploader_key']}"
                )

                if st.button("Iniciar proceso de importación"):
                    if uploaded_files:
                        # 1. Subimos a S3 (esta función debe devolver el ID que generó)
                        exito, execution_id = insertar_nuevas_muestras(uploaded_files)
                        
                        if exito:
                            # 2. Entramos en el bucle de espera activa
                            monitorizar_actualizacion_lambda(execution_id)
                    else:
                        st.warning("Selecciona archivos primero.")
                    
                st.info(
                    "**Requerimientos del archivo Excel:**\n"
                    "- Solo se aceptan archivos Excel, en formato `.xlsx` o `.xls`.\n"
                    "- Las 4 primeras filas de cada página serán ignoradas; pueden estar vacías.\n"
                    "- El orden de las variables debe ser exactamente el mostrado en la imagen de referencia.\n"
                    "- La columna `Compound Group` puede no existir, en ese caso se clasificacarán los compuestos nuevos como Otros.\n\n"
                )

                st.markdown("""
                        > **Detalles relevantes del proceso:**
                        > - Las muestras duplicadas no se añadirán.
                        > - La **fecha** de la muestra será extraída de la variable **`Sample Name`**.
                        > - No interrumpir el proceso de inserción.
                    """)

            with vacio_add:
                pass
        
        with delete_insertions_tab:            
            # 1. Obtener datos de la tabla UpdateLog y ordenamos las columnas
            df_logs = obtener_historial_updatelog()

            if df_logs.empty:
                st.warning("No se encontraron registros de ejecuciones anteriores.")
            else:
                tabla_eleccion, vacio_add, informacion = st.columns([1.5, 0.1, 1])

                with tabla_eleccion:
                    st.markdown("### Selecciona las inserciones específicas que deseas eliminar.")
                    
                    # Configuramos la tabla con selección
                    event = st.dataframe(
                        df_logs,
                        use_container_width=True,
                        hide_index=True,
                        on_select="rerun",
                        selection_mode="multi-row",
                        column_config={
                            "timestamp": st.column_config.TextColumn("Fecha/Hora"),
                            "execution_id": st.column_config.TextColumn("ID Ejecución"),
                            "excel_files": st.column_config.ListColumn("Archivos Excel"),
                            "records_affected": st.column_config.NumberColumn("Nº muestras insercción", format="%d"),
                            "number_of_files": st.column_config.NumberColumn("Nº de archivos", format="%d"),
                            "user": st.column_config.TextColumn("Ejecutado por"),
                        }
                    )

                    # 1. Inicializamos el estado al principio del tab para controlar la visibilidad
                    if 'ejecutando_revocacion' not in st.session_state:
                        st.session_state.ejecutando_revocacion = False
                    if 'id_nueva_operacion' not in st.session_state:
                        st.session_state.id_nueva_operacion = None

                    # 2. Lógica de selección
                    selected_rows = event.selection.rows

                    if selected_rows:
                        # Si la selección cambia, podríamos querer resetear el estado (opcional)
                        # ids_actuales = df_logs.iloc[selected_rows]['execution_id'].tolist()

                        # --- CASO A: EL PROCESO ESTÁ EN MARCHA (Sustituimos el panel por el monitor) ---
                        if st.session_state.ejecutando_revocacion:
                            st.write("")
                            st.write("---")
                            
                            # Aquí sale el monitor justo donde estaba el panel
                            monitorizar_actualizacion_lambda(
                                nuevo_id_esperado=st.session_state.id_nueva_operacion, 
                                is_revoke=True
                            )
                            
                            # Al terminar el monitor, reseteamos para que si quiere volver a borrar algo, el panel vuelva
                            st.session_state.ejecutando_revocacion = False
                            st.success("✅ Proceso finalizado con éxito.")
                            st.balloons()
                            st.rerun()

                        # --- CASO B: EL PROCESO NO HA EMPEZADO (Mostramos el panel de confirmación) ---
                        else:
                            st.write("")
                            st.write("---")
                            
                            # Cálculos
                            df_seleccionado = df_logs.iloc[selected_rows]
                            ids_a_revocar = df_seleccionado['execution_id'].tolist()
                            muestras_a_eliminar = df_seleccionado['records_affected'].sum()
                            total_actual = len(df_petrola)
                            total_final = total_actual - muestras_a_eliminar

                            # PANEL DE CONFIRMACIÓN                            
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                st.metric("Muestras actuales", f"{int(total_actual):,}")
                            with c2:
                                st.metric("Tras la operación", f"{int(total_final):,}", 
                                        delta=f"-{int(muestras_a_eliminar):,}", delta_color="inverse")
                            with c3:
                                st.metric("Lotes a borrar", len(ids_a_revocar))
                            
                            st.markdown(f"Después de esta operación, el sistema quedará con **{int(total_final):,}** muestras totales. Esta operación no se podrá revertir. ¿Está seguro?")

                            
                            if st.button(
                                "Confirmar y eliminar",
                                type="primary",
                                use_container_width=True,
                                disabled=st.session_state.confirmando_eliminacion  # se deshabilita tras el primer click
                            ):
                                st.session_state.confirmando_eliminacion = True  # bloquea inmediatamente

                                new_id = f"exec-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"
                                exito = eliminar_insercion_aws(ids_a_revocar, new_id)

                                if exito:
                                    st.session_state.ejecutando_revocacion = True
                                    st.session_state.id_nueva_operacion = new_id
                                    st.session_state.confirmando_eliminacion = False  # reset para la próxima vez
                                    st.rerun()
                                else:
                                    # Si falla, liberamos el bloqueo para que pueda reintentar
                                    st.session_state.confirmando_eliminacion = False
                                    st.rerun()

                    else:
                        # Si el usuario desmarca la tabla, nos aseguramos de limpiar el estado
                        st.session_state.ejecutando_revocacion = False

                with informacion:
                    st.write("")
                    st.write("")
                    st.write("")
                    st.write("")
                    st.info(
                        "**Pasos para el proceso de revocado:**\n\n"
                        "1. **Selección:** Marca en la tabla las ejecuciones que deseas eliminar del sistema.\n"
                        "2. **Confirmación:** Pulsa el botón para iniciar el proceso y espere unos segundos.\n"
                        "3. **Sincronización:** El sistema monitorizará el estado hasta que se complete la eliminación."
                    )
                    
                    st.markdown("""
                        > **Detalles relevantes del proceso:**
                        > - El revocado eliminará las particiones correspondientes en la capa **Gold**.
                        > - Se actualizará el registro en la tabla `Estado Actual` automáticamente.
                        > - Este proceso **no se puede deshacer** una vez finalizado.
                    """)

                with vacio_add:
                    pass
        
        
        with audit_tab:
        
            col_selector, col_table = st.columns([1, 3])
        
            with col_selector:
                tabla_seleccionada = st.selectbox(
                    "Selecciona una tabla",
                    options=list(TABLE_CONFIG.keys()),
                    index=0,               # UpdateLog por defecto
                    help="Elige qué tabla de auditoría quieres consultar."
                )

                st.info(
                    "**Tablas de Metadatos del Sistema:**\n\n"
                    "- **Registro de Actualizaciones**: Registro cronológico de todas las operaciones de inserción, "
                    "actualización y rollback realizadas sobre el sistema.\n\n"
                    "- **Registro de Datos Descartados**: Registro de todos los elementos (archivos, hojas o filas) "
                    "descartados durante los procesos de inserción por no superar la validación.\n\n"
                    "- **Estado Actual**: Estado actual del sistema. Indica el archivo maestro vigente "
                    "y si hay un proceso de inserción en curso."
                )
        
                if st.button("Refrescar datos", use_container_width=True):
                    st.cache_data.clear()
                    st.rerun()
        
            with col_table:
                config = TABLE_CONFIG[tabla_seleccionada]
                df_audit = config["fn"]()
        
                if df_audit.empty:
                    st.info("No hay registros disponibles para esta tabla.")
                else:
                    st.caption(f"{len(df_audit)} registros encontrados")
                    st.dataframe(df_audit, use_container_width=True, hide_index=True)


# Se filtra el Dataframe usando los filtros seleccionados
df_filtrado, orden = aplicar_filtros(df_petrola, filtros)


# Se muestran las estadisticas generadas una vez filtrado el dataframe
with metrics_placeholder.container():
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(
        f"<div class='metric-box'><div class='metric-value'>{len(df_filtrado)}  💧</div><div class='metric-label'>Muestras</div></div>",
        unsafe_allow_html=True
    )
    col2.markdown(
        f"<div class='metric-box'><div class='metric-value'>{len(df_filtrado['station_id'].unique())}  📡</div><div class='metric-label'>Estaciones</div></div>",
        unsafe_allow_html=True
    )
    col3.markdown(
        f"<div class='metric-box'><div class='metric-value'>{len(df_filtrado['name'].unique()) }  🧪</div><div class='metric-label'>Compuestos</div></div>",
        unsafe_allow_html=True
    )
    col4.markdown(
        f"<div class='metric-box'><div class='metric-value'>{df_filtrado['match_factor'].mean():.1f}  % </div><div class='metric-label'>Media Match Factor</div></div>",
        unsafe_allow_html=True
    )





with compuestos_tab:
    # ---------------------------------------------------------------------
    # ---------- PESTAÑA 1: Compuestos y Grupos (Gráficas) -----------------
    # ---------------------------------------------------------------------
    with grafica_match_bar:
        valor_barras_horizontales = [match_factor_sel[0], match_factor_sel[1]]
        mostrar_quesito = False # Se ha decido no mostrar esta grafica, se deja por si acaso se cambia de opinion
        plot_boxplot_match_factor(df_filtrado, filtros['familias'], grupos_color, valor_barras_horizontales, mostrar_quesito)

        
        
    with grafica_quesito:
        #if mostrar_quesito:
        #    grafica_quesito.text("")
        #    plot_top_grupos(df_filtrado, grupos_color)
        pass





with time_tab:
    # ---------------------------------------------------------------------
    # ---------- PESTAÑA 3: Evolución Temporal (Gráfica) ------------------
    # ---------------------------------------------------------------------
    with grafica_time_bar:
        plot_evolution_over_time(df_filtrado, orden, filtros, grupos_color)





with stations_tab:
    # ---------------------------------------------------------------------
    # -------------------PESTAÑA 2: Estaciones (Gráficas) ------------------
    # ---------------------------------------------------------------------
    with filtros_stations_tab:
        filtros_stations_tab.text("")
        st.markdown("<span style='font-weight: 900;'>Muestras detectadas por estación</span>", unsafe_allow_html=True)


        # Muestras por estación
        muestras_por_estacion = df_filtrado['station_id'].value_counts()


        df = muestras_por_estacion.reset_index()
        df.columns = ['station_id', 'n_muestras']
        estaciones_tipo = df_filtrado[['station_id', 'st_type']].drop_duplicates()
        df = df.merge(estaciones_tipo, on='station_id', how='left')
        df['color'] = df['station_id'].map(estaciones_color)

        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X('station_id:N', title='Estación'),
            y=alt.Y('n_muestras:Q', axis=alt.Axis(title=None)),
            color=alt.Color('color:N', scale=None),
            tooltip=[
                alt.Tooltip('station_id:N', title='Estación'),
                alt.Tooltip('n_muestras:Q', title='Nº de muestras'),
                alt.Tooltip('st_type:N', title='Tipo')
            ]

        ).properties(
            height=390
        )

        st.altair_chart(chart, use_container_width=True)

    with grafica_stations_tab:
        grafica_stations_tab.text("")
        st.markdown("<span style='font-weight: 900;'>Localización de Estaciones y Compuestos</span>",
                    unsafe_allow_html=True)
        plot_station_map_plotly(df_filtrado, estaciones_color)





with filtered_data_tab:
    # ---------------------------------------------------------------------
    # --------- PESTAÑA 4: Datos Filtrados (Filtros y Tabla) --------------
    # ---------------------------------------------------------------------
    filtered_data_tab.text("")
    n = st.selectbox("Número de muestras a mostrar", ["100","1000","10000","Todas"])

    # Omitimos mostrar estas columnas ya que no aportan demasiada información y solo hacen mas grande la tabla
    df_mostrar = df_filtrado.drop(columns=['periodo', 'x', 'y'])
    df_mostrar['sample_date'] = df_mostrar['sample_date'].dt.date
    n = len(df_mostrar) if n=="Todas" else int(n)

    # Mostramos la tabla sin restricciones de tamaño, se adaptará al espacio disponible
    st.dataframe(df_mostrar.head(n), height=540)
            
