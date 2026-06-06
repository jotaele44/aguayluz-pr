"""Correct WATERS parameter contract."""
BASE_URL="https://api.epa.gov/waters"
FORMAT_PARAM={"f":"json"}
PARAM_STYLE={
 "v1":"legacy p-prefix query params",
 "v4_get":"non-prefixed query params",
 "v4_post":"p_ body fields",
}
UPSTREAMDOWNSTREAM_V4_GET=["start_point","indexing_engine","search_type","start_nhdplusid"]
DRAINAGE_V1=["pgeometry","pcomid","pfeaturetype","poutput