package com.example.waterbusiness.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.List;

@Data
@Schema(description = "Water quality check request (11 numeric inputs)")
public class WaterQualityRequest {

    @NotNull(message = "必填")
    @JsonProperty("Water_Temperature_C")
    @Schema(description = "Water temperature (°C)", example = "24.5")
    private Double waterTemperatureC;

    @NotNull(message = "必填")
    @JsonProperty("pH")
    @Schema(description = "pH", example = "7.1")
    private Double pH;

    @NotNull(message = "必填")
    @JsonProperty("Dissolved_Oxygen_mg_L")
    @Schema(description = "Dissolved oxygen (mg/L)", example = "6.9")
    private Double dissolvedOxygenMgL;

    @NotNull(message = "必填")
    @JsonProperty("Conductivity_uS_cm")
    @Schema(description = "Conductivity (µS/cm)", example = "305.0")
    private Double conductivityUSCm;

    @NotNull(message = "必填")
    @JsonProperty("Turbidity_NTU")
    @Schema(description = "Turbidity (NTU)", example = "4.0")
    private Double turbidityNTU;

    @NotNull(message = "必填")
    @JsonProperty("Nitrate_mg_L")
    @Schema(description = "Nitrate (mg/L)", example = "1.2")
    private Double nitrateMgL;

    @NotNull(message = "必填")
    @JsonProperty("Ammonia_N_mg_L")
    @Schema(description = "Ammonia nitrogen (mg/L)", example = "0.18")
    private Double ammoniaNMgL;

    @NotNull(message = "必填")
    @JsonProperty("Total_Phosphorus_mg_L")
    @Schema(description = "Total phosphorus (mg/L)", example = "0.06")
    private Double totalPhosphorusMgL;

    @NotNull(message = "必填")
    @JsonProperty("COD_mg_L")
    @Schema(description = "COD (mg/L)", example = "16.5")
    private Double codMgL;

    @NotNull(message = "必填")
    @JsonProperty("BOD_mg_L")
    @Schema(description = "BOD (mg/L)", example = "3.1")
    private Double bodMgL;

    @NotNull(message = "必填")
    @JsonProperty("Heavy_Metals_Pb_ug_L")
    @Schema(description = "Lead Pb (µg/L)", example = "4.2")
    private Double heavyMetalsPbUgL;

    @NotBlank(message = "stationCode 必填，须为已在 monitor_station 登记的站点编码")
    @Schema(description = "Station code (required); must match registered station_code", example = "puget_12117000")
    private String stationCode;

    /** Optional: which metrics were observed (JSON field names); omit means all 11 observed */
    @JsonProperty("observed_fields")
    @Schema(description = "Optional observed field names for Python rule engine coverage")
    private List<String> observedFields;
}
