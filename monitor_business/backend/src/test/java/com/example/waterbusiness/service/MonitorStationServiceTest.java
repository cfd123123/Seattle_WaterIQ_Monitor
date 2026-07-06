package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.StationUpsertRequest;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.MonitorStationRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.server.ResponseStatusException;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MonitorStationServiceTest {

    @Mock
    private MonitorStationRepository monitorStationRepository;

    @Mock
    private UsgsSiteVerificationService usgsSiteVerificationService;

    @InjectMocks
    private MonitorStationService monitorStationService;

    @BeforeEach
    void stubUsgs() {
        lenient().doNothing().when(usgsSiteVerificationService).requireNwisSiteExistsIfConfigured(any());
    }

    @Test
    void create_whenStationCodeExists_throwsConflict() {
        when(monitorStationRepository.findByStationCode("s1"))
                .thenReturn(Optional.of(new MonitorStation()));

        StationUpsertRequest req = new StationUpsertRequest();
        req.setStationCode("s1");
        req.setLatitude(1.0);
        req.setLongitude(2.0);

        assertThatThrownBy(() -> monitorStationService.create(req))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(ex -> assertThat(((ResponseStatusException) ex).getStatusCode().value()).isEqualTo(409));

        verify(monitorStationRepository, never()).saveAndFlush(any());
    }

    @Test
    void create_whenNew_persists() {
        when(monitorStationRepository.findByStationCode("s1")).thenReturn(Optional.empty());
        when(monitorStationRepository.saveAndFlush(any())).thenAnswer(inv -> {
            MonitorStation s = inv.getArgument(0);
            s.setId(10L);
            return s;
        });

        StationUpsertRequest req = new StationUpsertRequest();
        req.setStationCode("s1");
        req.setLatitude(1.0);
        req.setLongitude(2.0);

        monitorStationService.create(req);

        ArgumentCaptor<MonitorStation> cap = ArgumentCaptor.forClass(MonitorStation.class);
        verify(monitorStationRepository).saveAndFlush(cap.capture());
        assertThat(cap.getValue().getStationCode()).isEqualTo("s1");
    }
}
