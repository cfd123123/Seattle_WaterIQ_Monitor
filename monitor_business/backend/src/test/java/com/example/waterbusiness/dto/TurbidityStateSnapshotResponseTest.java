package com.example.waterbusiness.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class TurbidityStateSnapshotResponseTest {

  private final ObjectMapper objectMapper = new ObjectMapper();

  @Test
  void deserializesPythonKey63680() throws Exception {
    TurbidityStateSnapshotResponse snap =
        objectMapper.readValue(
            "{\"site_no\":\"12117500\",\"63680\":0.6,\"state\":\"Normal\"}",
            TurbidityStateSnapshotResponse.class);
    assertThat(snap.getTurbidityNtu()).isEqualTo(0.6);
  }

  @Test
  void serializesTurbidityNtuForUi() throws Exception {
    TurbidityStateSnapshotResponse snap = new TurbidityStateSnapshotResponse();
    snap.setSiteNo("12117500");
    snap.setTurbidityNtu(0.6);
    assertThat(objectMapper.writeValueAsString(snap)).contains("\"turbidityNtu\":0.6");
  }
}
